# Investigación: Pipeline de Aves de Nantes

**Feature**: `001-nantes-birds-pipeline` | **Fecha**: 2026-10-10

Todos los puntos NEEDS CLARIFICATION del Contexto Técnico se resuelven a continuación.

---

## 1. API v1 de iNaturalist — Ingesta Incremental

### Decisión
Usar `created_d1` + `created_d2` (cadenas de fecha ISO 8601, `YYYY-MM-DD`) para filtrar las
observaciones por fecha de creación. Guardar el watermark como marca de tiempo UTC en SSM; en
cada ejecución derivar `created_d1 = last_successful_run_date` y `created_d2 = today`.

### Hallazgos

**Endpoint**: `GET https://api.inaturalist.org/v1/observations`

**Parámetros del bounding box** (confirmados):
```
swlat=46.8600781&swlng=-2.6257395&nelat=47.8359431&nelng=-0.9466615
```

**Parámetros del filtro incremental**:
- `created_d1` — fecha límite inferior (inclusiva), formato `YYYY-MM-DD`
- `created_d2` — fecha límite superior (inclusiva), formato `YYYY-MM-DD`
- `updated_since` — datetime ISO 8601 para registros actualizados después de una marca de
  tiempo (alternativa para una ingesta incremental basada en actualizaciones; no se usa en la
  v1 porque la spec apunta a la fecha de creación)

**Taxón**: Aves = `taxon_id=3` (clase Aves, ID de taxón de iNaturalist confirmado)

**Paginación**:
- `page` (empieza en 1) + `per_page` (máx. 200)
- La respuesta incluye el entero `total_results` → se derivan `ceil(total_results / per_page)` páginas
- Rate limit: 100 req/min documentado; ~1 req/s es un valor por defecto conservador y seguro
  según la constitución

**Campos clave del objeto de respuesta**:
```json
{
  "id": 123456,
  "created_at": "2024-05-01T10:23:00+00:00",
  "observed_on": "2024-04-30",
  "observed_time_zone": "Europe/Paris",
  "quality_grade": "research",
  "location": "47.2184,-1.5536",        // cadena "lat,lng" — hay que separarla
  "positional_accuracy": 10,
  "taxon": {
    "id": 18793,
    "name": "Larus michahellis",
    "preferred_common_name": "Yellow-legged Gull",
    "rank": "species",
    "threatened": false
  },
  "user": {
    "id": 9876,
    "login": "birder42",
    "name": "Jane Birder"
  }
}
```

**Valores válidos de `quality_grade`**: `research`, `needs_id`, `casual` (confirmado — coincide con FR-010)

**Límite estricto de paginación**: La API impone un **tope de 10.000 resultados totales** por
ventana de consulta (`page * per_page ≤ 10,000`; la paginación falla más allá de la página
333). Con los volúmenes diarios de Nantes nunca se alcanza este tope, pero el diseño debe usar
la estrategia de cursor `id_above` como salvaguarda:

```
Strategy: id_above cursor
  1. First call: page=1, per_page=200, order_by=id, order=asc
  2. Save max(id) from batch → last_id
  3. Subsequent calls: id_above=last_id, per_page=200 (no page param)
  4. Stop when len(results) < per_page (last page)
```

Esto evita el tope de 10k e impide observaciones duplicadas por desplazamientos de página a
mitad de la ejecución.

**Trampas**:
- `location` es una cadena `"lat,lng"`, no un objeto; hay que separarla en staging
- `preferred_common_name` puede faltar (null) en taxones poco comunes — aceptable según la spec
- Puede haber solapamiento de paginación si se crean observaciones durante la ejecución; la
  deduplicación por `id` en staging lo resuelve (FR-014) y el cursor `id_above` lo mitiga aún más
- `created_at` incluye zona horaria; se castea a UTC en staging
- `created_d1`/`created_d2` también aceptan `YYYY-MM-DDTHH:MM:SS` para precisión inferior al
  día — usar el formato datetime completo en el watermark para no re-ingestar días parciales

### Alternativas consideradas
- Usar `updated_since` para una ingesta incremental que incluya actualizaciones: aplazado a la
  v2; complica la lógica de deduplicación y la spec solo exige capturar observaciones recién
  creadas (FR-002)
- Solo paginación por páginas: descartada por el tope de 10k; el cursor `id_above` es más robusto
- GraphQL / API de exportación: requiere autenticación, desproporcionado para este volumen

---

## 2. Patrón de Watermark en Lambda (SSM Parameter Store)

### Decisión
Guardar un único parámetro SSM de tipo `String` (`/birds-pipeline/last_successful_run_date`)
con la fecha de la última ingesta exitosa en formato `YYYY-MM-DD`. Leerlo antes de la ejecución
y escribirlo atómicamente cuando todas las escrituras en S3 hayan tenido éxito. El rol IAM de
Lambda se restringe al ARN de ese único parámetro.

### Justificación
- Los parámetros SSM `String` están en la capa gratuita (standard tier), son duraderos y admiten
  un put atómico
- Mantiene el estado fuera de Lambda (función sin estado) sin añadir el coste/complejidad de DynamoDB
- Restringir a un solo parámetro cumple la restricción de mínimo privilegio (constitución IV + FR-002)

### Patrón

```python
# ssm_watermark.py
def get_watermark(ssm_client, param_name: str) -> str | None:
    try:
        resp = ssm_client.get_parameter(Name=param_name)
        return resp["Parameter"]["Value"]   # "YYYY-MM-DD" or None on first run
    except ssm_client.exceptions.ParameterNotFound:
        return None

def put_watermark(ssm_client, param_name: str, value: str) -> None:
    ssm_client.put_parameter(Name=param_name, Value=value,
                              Type="String", Overwrite=True)
```

---

## 3. Adaptador Comunitario dbt-athena

### Decisión
Usar `dbt-athena-community` (no el paquete `dbt-athena` de AWS, obsoleto). Configurar los
modelos con `file_format = 'parquet'`, `write_compression = 'snappy'` e
`incremental_strategy = 'insert_overwrite'` particionado por `year`/`month` para `fct_observations`.

### Hallazgos

**Paquete**: `dbt-athena` (PyPI; `dbt-athena-community` es ahora un envoltorio de
compatibilidad — instalar `dbt-athena` directamente en proyectos nuevos; soporta dbt-core 1.5+)

**Campos obligatorios de `profiles.yml`**:
```yaml
birds_pipeline:
  target: dev
  outputs:
    dev:
      type: athena
      region_name: eu-west-3          # Paris region (closest to Nantes)
      s3_staging_dir: s3://my-bucket/athena-results/
      s3_data_dir: s3://my-bucket/processed/
      database: awsdatacatalog         # Glue catalog
      schema: birds_dbt               # Glue database name
      threads: 4
```

**Configuración Parquet + Snappy a nivel de modelo** (añadir al bloque `config` de cada modelo
o a `dbt_project.yml`):
```sql
{{ config(
    materialized = 'incremental',
    incremental_strategy = 'insert_overwrite',
    partitioned_by = ['year', 'month'],
    format = 'parquet',
    write_compression = 'snappy'
) }}
```

Nota: en dbt-athena la clave es `format` (no `file_format`).

**Estrategia incremental**: `insert_overwrite` es la estrategia recomendada para Athena;
sobrescribe particiones Hive de forma atómica. `merge` requiere tablas Iceberg (fuera del
alcance de la v1). Para tablas de hechos de solo inserción, `insert_overwrite` sobre las
particiones `(year, month)` es seguro e idempotente.

**Tabla externa (fuente JSON raw)**:
El JSON raw en S3 se expone como tabla externa de Athena mediante un crawler de AWS Glue
(asunto de infraestructura) o un DDL manual. En dbt se referencia como `source` en `sources.yml`:
```yaml
sources:
  - name: raw_inaturalist
    database: awsdatacatalog
    schema: birds_raw            # Glue database for raw zone
    tables:
      - name: observations
        description: "Raw JSON observations partitioned by year/month"
        external: true
```
dbt-athena lee las tablas externas con normalidad; no gestiona su DDL.

**Glue Catalog**: dbt-athena crea y actualiza las tablas de Glue automáticamente al ejecutar
`dbt run`. No hace falta DDL manual para los modelos gestionados (no externos).

**Tabla externa (fuente JSON raw)**: Usar el paquete `dbt-external-tables`:
```yaml
# sources.yml
sources:
  - name: raw_inaturalist
    schema: birds_raw
    tables:
      - name: observations
        external:
          location: s3://my-bucket/raw/inaturalist/observations/
          row_format: >
            SERDE 'org.openx.data.jsonserde.JsonSerDe'
          partitions:
            - name: year
              data_type: string
            - name: month
              data_type: string
```
Registrar con: `dbt run-operation stage_external_sources`

> **Corrección (2026-10-11):** `dbt-labs/dbt_external_tables` no implementa Athena, así que
> `stage_external_sources` falla con este adaptador. La tabla raw se crea con la macro
> `dbt_birds/macros/create_raw_observations_table.sql` (DDL con *partition projection*), que
> además hace visibles las particiones nuevas de cada mes sin `MSCK REPAIR`. El paquete se
> retiró de `packages.yml` y el bloque `external:` de `sources.yml`.

**Trampas**:
- `s3_staging_dir` guarda los resultados de consultas de Athena (temporales); `s3_data_dir`
  guarda los datos de los modelos dbt
- Los nombres de columna con puntos deben renombrarse en staging (limitación de Athena/Parquet)
- `insert_overwrite` reescribe particiones completas — asegurarse de que `fct_observations`
  esté particionada antes de las ejecuciones incrementales; la primera ejecución debe usar
  `--full-refresh`
- Athena no soporta `DELETE` ni `UPDATE` de forma nativa; merge requiere Iceberg (aplazado)
- Límite de 100 particiones en tablas Hive; year+month da ~12–24 particiones — muy por debajo
  del límite
- El parseo del JSON raw requiere `org.openx.data.jsonserde.JsonSerDe` para los campos anidados
  complejos

### Alternativas consideradas
- Paquete `dbt-athena` nativo de AWS: obsoleto en favor del adaptador comunitario; descartado
- Tablas Iceberg con estrategia `merge`: soporta upserts reales pero añade complejidad operativa
  y coste; aplazado a la v2 si se necesita una ingesta incremental basada en actualizaciones

---

## 4. Power BI + Athena en Modo Import

### Decisión
Conectar Power BI a Athena mediante el **driver ODBC de AWS Athena** (Simba/Amazon). Usar el
modo **Import** con actualización programada diaria. Sin DirectQuery (excluido según los
supuestos de la spec).

### Justificación
- El modo Import cachea los datos en el motor en memoria de Power BI → visuales en menos de un
  segundo sin coste de Athena por consulta
- Actualización diaria alineada con la cadencia de ingesta (SC-001: datos disponibles en 24 h)
- DirectQuery generaría coste de escaneo en Athena en cada interacción con un visual
  (descartado por la spec)

### Configuración de la conexión (detalle del quickstart)
1. Instalar el driver ODBC de Amazon Athena (64 bits)
2. Power BI Desktop → Get Data → ODBC → DSN apuntando al esquema `birds_dbt` de Athena
3. Seleccionar `fct_observations`, `dim_species`, `dim_users`, `dim_date`
4. Definir las relaciones en la vista Model (esquema estrella)
5. Publicar en Power BI Service → configurar la actualización programada (diaria, después de la ingesta)

---

## Tabla Resumen

| Pregunta | Respuesta |
|----------|-----------|
| Parámetros del filtro incremental | `created_d1` / `created_d2` (YYYY-MM-DD) |
| ID de taxón de Aves | `3` |
| `per_page` máximo | `200` |
| Rate limit (seguro) | ~1 req/s (100 req/min documentado) |
| Formato de `location` | cadena `"lat,lng"` — se separa en staging |
| Valores de `quality_grade` | `research`, `needs_id`, `casual` |
| Paquete adaptador de dbt | `dbt-athena-community` |
| Estrategia incremental de dbt | `insert_overwrite` particionado por `(year, month)` |
| Compresión Parquet | Snappy (`write_compression = 'snappy'`) |
| Conexión de Power BI | Athena ODBC (Simba), modo Import, actualización diaria |
