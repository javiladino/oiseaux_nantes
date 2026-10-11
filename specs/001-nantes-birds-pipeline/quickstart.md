# Guía de Validación Rápida: Pipeline de Aves de Nantes

**Feature**: `001-nantes-birds-pipeline` | **Fecha**: 2026-10-10

Esta guía documenta escenarios de validación ejecutables que demuestran que cada capa del
pipeline funciona de extremo a extremo. No es una guía de implementación — para las
definiciones de los modelos ver [data-model.md](data-model.md), para los detalles de la API ver
[contracts/inaturalist-api.md](contracts/inaturalist-api.md).

---

## Requisitos Previos

| Requisito | Comprobación |
|-----------|--------------|
| AWS CLI configurado (`eu-west-3`) | `aws sts get-caller-identity` |
| El bucket S3 existe con el prefijo correcto | `aws s3 ls s3://{bucket}/raw/inaturalist/` |
| Parámetro SSM creado (o ausente en la primera ejecución) | `aws ssm get-parameter --name /birds-pipeline/last_successful_run_date` |
| Existen el workgroup de Athena + las bases de datos de Glue (`birds_raw`, `birds_dbt`) | Consola de AWS / Athena |
| Proyecto dbt instalado y profiles.yml configurado | `dbt debug` |
| Python 3.11+ y dependencias de Lambda instaladas localmente | `python --version` |

---

## Escenario 1: Ingesta de Primera Ejecución (Historia 1, AC-1)

**Qué demuestra**: FR-001/002/003, SC-001, SC-006 (línea base de la primera ejecución)

### Pasos

```bash
# 1. Confirmar que no existe watermark (primera ejecución)
aws ssm get-parameter --name /birds-pipeline/last_successful_run_date
# Esperado: error ParameterNotFound

# 2. Invocar Lambda (en local o con un evento de prueba en la consola de AWS)
aws lambda invoke \
  --function-name birds-inaturalist-ingestion \
  --payload '{}' \
  response.json
cat response.json
# Esperado: {"statusCode": 200, "body": "Ingested N observations"}

# 3. Verificar que se crearon archivos en S3 bajo la partición del año/mes actual
aws s3 ls s3://{bucket}/raw/inaturalist/observations/ --recursive
# Esperado: archivos bajo year=YYYY/month=MM/

# 4. Comprobar que un archivo contiene observaciones JSON válidas
aws s3 cp s3://{bucket}/raw/inaturalist/observations/year=.../month=.../{file}.json - | head -1 | python3 -m json.tool
# Esperado: JSON bien formado con los campos id, created_at, location, taxon, user

# 5. Confirmar que el watermark se actualizó
aws ssm get-parameter --name /birds-pipeline/last_successful_run_date
# Esperado: {"Parameter": {"Value": "YYYY-MM-DDTHH:MM:SS"}}
```

### Resultado Esperado
- Uno o más archivos NDJSON presentes en S3 bajo la partición correcta
- Cada línea es un objeto de observación JSON válido
- El parámetro SSM contiene la marca de tiempo de la ejecución de hoy
- No hay valores de `id` duplicados entre archivos (comprobación puntual)

---

## Escenario 2: Ejecución Incremental — Sin Duplicados (Historia 1, AC-2/3/4)

**Qué demuestra**: FR-002/014, SC-002/006

### Pasos

```bash
# 1. Anotar el número actual de archivos en S3
aws s3 ls s3://{bucket}/raw/inaturalist/observations/ --recursive | wc -l
# Anotar: file_count_before

# 2. Invocar Lambda de nuevo (el mismo día — debería encontrar 0 o pocas observaciones nuevas)
aws lambda invoke \
  --function-name birds-inaturalist-ingestion \
  --payload '{}' \
  response2.json
cat response2.json

# 3. Verificar que el número de archivos no cambió (si hay 0 obs. nuevas) o aumentó en uno
aws s3 ls s3://{bucket}/raw/inaturalist/observations/ --recursive | wc -l
# Esperado: file_count_before (si 0 nuevas) o file_count_before + 1

# 4. Verificar que los IDs de observación son únicos entre todos los archivos (consulta Athena):
# SELECT COUNT(*), COUNT(DISTINCT id) FROM raw_inaturalist.observations
# Esperado: COUNT(*) = COUNT(DISTINCT id)
```

### Resultado Esperado
- Ningún archivo nuevo si no hay observaciones nuevas desde la última ejecución
- Re-ejecutar produce el mismo estado final (idempotente)
- Sin valores de `id` duplicados entre particiones

---

## Escenario 3: Validación del Modelo de Staging en dbt (Historia 2, AC-1)

**Qué demuestra**: FR-004, FR-008/010/015, SC-004

### Pasos

```bash
# 1. Crear la tabla raw externa (idempotente; usa partition projection, así que las
#    particiones de cada mes son visibles sin registrarlas)
cd dbt_birds
BIRDS_S3_BUCKET=<bucket> dbt run-operation create_raw_observations_table

# 2. Ejecutar el modelo de staging
dbt run --select stg_inaturalist__observations

# 3. Ejecutar los tests de staging
dbt test --select stg_inaturalist__observations
# Esperado: todos los tests pasan (0 fallos, 0 avisos)

# 4. Verificar el aplanado en la consola de Athena o con dbt:
# SELECT observation_id, latitude, longitude, taxon_scientific_name, user_login
# FROM birds_dbt.stg_inaturalist__observations LIMIT 5
# Esperado: todas las columnas pobladas (latitude/longitude como DOUBLE, no la cadena "lat,lng")
```

### Resultado Esperado
- `dbt test` informa 0 fallos
- `observation_id` es único y no nulo
- `latitude`/`longitude` son columnas DOUBLE separadas
- `quality_grade` ∈ {research, needs_id, casual}

---

## Escenario 4: Modelo Intermedio — Validación del Bounding Box (Historia 2, AC-2)

**Qué demuestra**: FR-005/006/007, SC-003

### Pasos

```bash
# 1. Ejecutar el modelo intermedio
dbt run --select int_observations__geospatial_enriched

# 2. Ejecutar los tests, incluido el test bbox personalizado
dbt test --select int_observations__geospatial_enriched
# Esperado: todos los tests pasan, incluido assert_observations_within_nantes_bbox

# 3. Verificar la contención en el bbox en Athena:
# SELECT MIN(latitude), MAX(latitude), MIN(longitude), MAX(longitude)
# FROM birds_dbt.int_observations__geospatial_enriched
# Esperado: lat ∈ [46.86, 47.84], lng ∈ [-2.63, -0.95]

# 4. Verificar la distribución de observation_period:
# SELECT observation_period, COUNT(*) FROM birds_dbt.int_observations__geospatial_enriched
# GROUP BY observation_period ORDER BY 2 DESC
# Esperado: 4 filas, todos los períodos presentes (Madrugada/Mañana/Tarde/Noche)

# 5. Verificar is_research_grade:
# SELECT is_research_grade, quality_grade, COUNT(*)
# FROM birds_dbt.int_observations__geospatial_enriched
# GROUP BY 1, 2
# Esperado: is_research_grade=true solo donde quality_grade='research'
```

### Resultado Esperado
- 0 registros fuera del bounding box de Nantes
- Los 4 valores de `observation_period` presentes
- `is_research_grade` derivado correctamente de `quality_grade`

---

## Escenario 5: Capa de Marts Completa — Integridad del Esquema Estrella (Historia 2, AC-3/4/5)

**Qué demuestra**: FR-008/009/011/012, SC-002/004

### Pasos

```bash
# 1. Ejecutar el DAG completo de dbt (primera ejecución: usar --full-refresh para los modelos incrementales)
dbt run --full-refresh
# O, para ejecuciones incrementales posteriores:
dbt run

# 2. Ejecutar todos los tests
dbt test
# Esperado: 0 fallos en todos los modelos

# 3. Verificar la unicidad de la clave primaria en Athena:
# SELECT COUNT(*), COUNT(DISTINCT observation_id) FROM birds_dbt.fct_observations
# Esperado: ambos recuentos iguales

# 4. Verificar la integridad referencial (sin FKs huérfanas):
# SELECT COUNT(*) FROM birds_dbt.fct_observations f
# LEFT JOIN birds_dbt.dim_species s ON f.species_key = s.species_key
# WHERE s.species_key IS NULL
# Esperado: 0

# Repetir para dim_users y dim_date

# 5. Verificar que dim_date cubre todo el rango de observaciones:
# SELECT MIN(date_key), MAX(date_key) FROM birds_dbt.dim_date
# frente a
# SELECT MIN(observed_on), MAX(observed_on) FROM birds_dbt.fct_observations
# Esperado: rango de dim_date ⊇ rango de observed_on en fct_observations

# 6. Verificar las 3 métricas analíticas (FR-012):
# SELECT
#   COUNT(*) AS total_observations,
#   COUNT(DISTINCT species_key) AS distinct_species,
#   SUM(CASE WHEN is_research_grade THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS research_grade_pct
# FROM birds_dbt.fct_observations
# Esperado: 3 valores numéricos, research_grade_pct entre 0 y 100
```

### Resultado Esperado
- `dbt test` pasa al 100 % en todos los modelos de marts
- Sin `observation_id` duplicados en `fct_observations`
- Todas las relaciones FK intactas
- `dim_date` cubre por completo el rango de fechas de observación
- Las 3 métricas analíticas devuelven valores válidos

---

## Escenario 6: Actualización End-to-End en Power BI (Historia 3)

**Qué demuestra**: FR-012/013, SC-001/005

### Pasos

1. Abrir Power BI Desktop
2. Conectar por ODBC (driver de Amazon Athena):
   - Servidor: `athena.eu-west-3.amazonaws.com`
   - Base de datos: `birds_dbt`
3. Importar estas tablas: `fct_observations`, `dim_species`, `dim_users`, `dim_date`
4. Definir las relaciones en la vista Model (ver [contracts/dbt-models.md](contracts/dbt-models.md))
5. Crear los 3 visuales requeridos:
   - **Visual de mapa**: Representar `latitude`/`longitude` de `fct_observations`; segmentador de filtro sobre `dim_species[common_name]`
   - **Tendencia estacional**: Gráfico de líneas/barras de `COUNT(observation_id)` por `dim_date[month_name]` coloreado por `dim_date[biological_season]`
   - **Tabla de ranking**: `dim_species[common_name]`, `COUNT(observation_id)` DESC + `dim_users[login]`, `COUNT(observation_id)` DESC
6. Publicar en Power BI Service
7. Configurar la actualización programada (diaria, a una hora posterior a la ejecución de Lambda por EventBridge)

### Resultado Esperado
- El mapa muestra las observaciones de aves geolocalizadas dentro del límite de Nantes
- La tendencia estacional muestra los recuentos mensuales coloreados por `Primavera`/`Verano`/`Otoño`/`Invierno`
- La tabla de ranking lista las especies y los observadores principales
- Tras re-ejecutar el pipeline, la actualización del dataset trae los datos nuevos sin intervención manual (SC-001)

---

## Escenario 7: Idempotencia ante Fallos (SC-006)

**Qué demuestra**: FR-003/014, SC-006

### Pasos

```bash
# 1. Simular un fallo parcial de Lambda (fijar el timeout de Lambda en 5 s — menos que una ejecución normal)
# Después invocar Lambda → debería fallar a mitad de la paginación

# 2. Verificar que el watermark de SSM NO se actualizó
aws ssm get-parameter --name /birds-pipeline/last_successful_run_date
# Esperado: el mismo valor que antes de la ejecución fallida

# 3. Restaurar el timeout normal de Lambda (180 s)
# Re-invocar Lambda — debería partir del mismo watermark y completarse con normalidad

# 4. Comprobar que no hay IDs de observación duplicados en S3/Athena
# (La misma consulta de Athena que en el Escenario 2, Paso 4)
# Esperado: COUNT(*) = COUNT(DISTINCT id)
```

### Resultado Esperado
- La ejecución fallida deja el watermark sin cambios
- La re-ejecución se completa correctamente desde el mismo watermark
- Sin valores de `observation_id` duplicados en ninguna capa

---

## Validación en CI (GitHub Actions)

Cada PR que modifica `dbt_birds/` dispara:

```yaml
# .github/workflows/dbt_ci.yml
- run: dbt compile
- run: dbt test --select state:modified+
```

Un `dbt test` fallido debe bloquear el merge del PR (constitución III). Revisar el badge de
estado del workflow o la pestaña Actions antes de hacer merge.
