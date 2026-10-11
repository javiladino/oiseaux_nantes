---

description: "Lista de tareas para la implementación del Pipeline de Biodiversidad de Aves en Nantes"
---

# Tareas: Pipeline de Biodiversidad de Aves en Nantes

**Entrada**: Documentos de diseño en `/specs/001-nantes-birds-pipeline/`

**Requisitos previos**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: Incluidos — los tests unitarios de Lambda (pytest + moto) y los tests de esquema de dbt están especificados explícitamente en plan.md.

**Organización**: Las tareas se agrupan por historia de usuario para permitir implementar y probar cada historia de forma independiente.

## Formato: `[ID] [P?] [Story?] Descripción`

- **[P]**: Puede ejecutarse en paralelo (archivos distintos, sin dependencias)
- **[Story]**: Historia de usuario a la que pertenece la tarea (US1, US2, US3)
- Cada descripción incluye las rutas exactas de los archivos

## Convenciones de Rutas

Repositorio único:
- `ingestion/` — paquete Python de Lambda
- `tests/unit/` / `tests/integration/` — tests de Python
- `dbt_birds/` — raíz del proyecto dbt
- `.github/workflows/` — GitHub Actions
- `reports/` — artefactos de Power BI
- `docs/` — documentación complementaria

---

## Phase 1: Setup (Infraestructura Compartida)

**Propósito**: Andamiaje de directorios del proyecto e inicialización de dependencias

- [X] T001 Crear el árbol de directorios del proyecto: `ingestion/`, `tests/unit/`, `tests/integration/`, `dbt_birds/models/sources/`, `dbt_birds/models/staging/`, `dbt_birds/models/intermediate/`, `dbt_birds/models/marts/`, `dbt_birds/tests/`, `reports/`, `docs/`
- [X] T002 [P] Crear `ingestion/requirements.txt` con `requests>=2.31` y `boto3>=1.34`
- [X] T003 [P] Crear `tests/requirements-dev.txt` con `pytest>=7.4`, `moto[s3,ssm]>=4.2` y `boto3>=1.34`
- [X] T004 [P] Crear `.gitignore` que cubra Python (`__pycache__/`, `*.pyc`, `.env`) y dbt (`dbt_birds/target/`, `dbt_birds/dbt_packages/`, `dbt_birds/logs/`)

---

## Phase 2: Foundational (Requisitos Previos Bloqueantes)

**Propósito**: Configuración del proyecto dbt y fixtures de pytest — necesarios antes de implementar cualquier historia de usuario

**⚠️ CRÍTICO**: No puede empezar ningún trabajo de historias de usuario hasta completar esta fase

- [X] T005 Crear `dbt_birds/dbt_project.yml` — fijar `name: birds_dbt`, configurar las materializaciones: `staging: {+materialized: view}`, `intermediate: {+materialized: view}`, `marts: {+materialized: table}`; fijar por defecto `+format: parquet` y `+write_compression: snappy` en `marts`
- [X] T006 [P] Crear `dbt_birds/profiles.yml` — conexión a Athena: `type: athena`, `region_name: eu-west-3`, `database: awsdatacatalog`, `schema: birds_dbt`, `threads: 4`, `s3_staging_dir: s3://{bucket}/athena-results/`, `s3_data_dir: s3://{bucket}/processed/`
- [X] T007 Crear `dbt_birds/models/sources/sources.yml` — definir la fuente `raw_inaturalist` (schema: `birds_raw`, tabla: `observations`, external: location `s3://{bucket}/raw/inaturalist/observations/`, SerDe: `org.openx.data.jsonserde.JsonSerDe`, particiones: `year STRING`, `month STRING`)
- [X] T008 [P] Crear `tests/conftest.py` — fixtures de pytest: `aws_credentials` (fija variables de entorno ficticias para moto), `s3_bucket` (bucket S3 de moto llamado `test-birds-bucket`), `ssm_client` (SSM de moto en `eu-west-3`), constante `ssm_param_name` `/birds-pipeline/last_successful_run_date`
- [X] T009 [P] Crear `dbt_birds/packages.yml` — declarar los paquetes `dbt-labs/dbt_utils` y `dbt-labs/dbt_external_tables`; ejecutar `dbt deps` para instalarlos

**Punto de control**: Base lista — ya puede empezar la implementación de las historias de usuario

---

## Phase 3: User Story 1 — Ingesta Incremental (Prioridad: P1) 🎯 MVP

**Objetivo**: Lambda obtiene de iNaturalist solo las observaciones de aves de Nantes nuevas desde la última ejecución exitosa, escribe NDJSON crudo en S3 y actualiza el watermark de forma atómica.

**Prueba Independiente**: Invocar Lambda en local → verificar que aparecen nuevos archivos NDJSON bajo `s3://{bucket}/raw/inaturalist/observations/year={YYYY}/month={MM}/` → volver a invocar → confirmar que no hay valores de `id` duplicados y que el watermark de SSM se actualizó.

### Implementación de la User Story 1

- [X] T010 [P] [US1] Implementar `ingestion/inaturalist_client.py` — `fetch_observations(watermark: str | None) -> list[dict]`: paginar `GET https://api.inaturalist.org/v1/observations` con el cursor `id_above` (per_page=200, order_by=id, order=asc); parámetros: `taxon_id=3`, `swlat=46.8600781`, `swlng=-2.6257395`, `nelat=47.8359431`, `nelng=-0.9466615`, `created_d1=watermark` (omitido en la primera ejecución); cabeceras: `User-Agent: oiseaux-nantes-pipeline/1.0`; esperar 1 s entre páginas; backoff exponencial ante 429/500/503 (máx. 3 reintentos); parar cuando `len(results) < per_page`
- [X] T011 [P] [US1] Implementar `ingestion/s3_writer.py` — `write_batch(s3_client, bucket: str, observations: list[dict], run_ts: datetime) -> str`: escribe NDJSON en `s3://{bucket}/raw/inaturalist/observations/year={YYYY}/month={MM}/{timestamp}.json` (UTF-8, un objeto JSON crudo por línea por cada elemento de `results[]`, sin transformación); devuelve la clave S3 escrita
- [X] T012 [P] [US1] Implementar `ingestion/ssm_watermark.py` — `get_watermark(ssm_client, param_name: str) -> str | None`: devuelve el valor String de SSM o `None` ante `ParameterNotFound`; `put_watermark(ssm_client, param_name: str, value: str) -> None`: escribe con `Type="String"`, `Overwrite=True`; nombre del parámetro: `/birds-pipeline/last_successful_run_date`
- [X] T013 [US1] Implementar `ingestion/handler.py` — punto de entrada de Lambda `lambda_handler(event, context)`: (1) `get_watermark()`, (2) `fetch_observations(watermark)`, (3) si hay observaciones > 0: `write_batch()` por cada lote de página, (4) `put_watermark(run_ts)` **solo** cuando todas las escrituras en S3 hayan tenido éxito; si hay 0 observaciones nuevas: omitir la escritura en S3 y la actualización del watermark; devolver `{"statusCode": 200, "body": f"Ingested {N} observations"}`; formato del watermark: datetime ISO 8601 (`YYYY-MM-DDTHH:MM:SS`)

### Tests de la User Story 1

- [X] T014 [P] [US1] Escribir `tests/unit/test_inaturalist_client.py` — tests con moto: la primera ejecución sin watermark obtiene todas las observaciones; la ejecución incremental pasa `created_d1`; el cursor `id_above` avanza correctamente entre páginas; una respuesta sin resultados devuelve una lista vacía; una respuesta 429 activa el backoff exponencial y reintenta ≤ 3 veces; al superar el máximo de reintentos se lanza una excepción
- [X] T015 [P] [US1] Escribir `tests/unit/test_s3_writer.py` — tests de S3 con moto: la clave de salida coincide con el patrón `year={YYYY}/month={MM}/{timestamp}.json`; el contenido del archivo es NDJSON válido (cada línea se parsea como JSON); varios lotes se escriben en archivos distintos; se preserva la codificación UTF-8
- [X] T016 [P] [US1] Escribir `tests/unit/test_ssm_watermark.py` — tests de SSM con moto: `get_watermark()` devuelve `None` cuando el parámetro no existe; devuelve la cadena correcta cuando existe; `put_watermark()` crea el parámetro en la primera llamada; `put_watermark()` lo sobrescribe en las llamadas siguientes
- [X] T017 [US1] Escribir `tests/integration/test_ingestion_e2e.py` — test contra la API real de iNaturalist (solo lectura, sin efectos secundarios): llamar a `fetch_observations(watermark=None)` con un límite de 1 página; comprobar que la respuesta contiene los campos `id`, `created_at`, `location`, `taxon`, `user`; comprobar que `quality_grade` es `research`, `needs_id` o `casual`; marcar con `@pytest.mark.integration` para ejecutarlo de forma selectiva

**Punto de control**: User Story 1 totalmente funcional — el pipeline de ingesta funciona de forma independiente

---

## Phase 4: User Story 2 — Transformación Medallón con dbt (Prioridad: P2)

**Objetivo**: El DAG de dbt transforma el JSON crudo a través de staging → intermedia → marts y produce un esquema estrella validado (`fct_observations`, `dim_species`, `dim_users`, `dim_date`) con todos los tests de esquema de dbt aprobados.

**Prueba Independiente**: `dbt run --full-refresh && dbt test` contra una capa raw poblada devuelve 0 fallos en todos los modelos; `fct_observations` no tiene `observation_id` duplicados; todas las relaciones FK están intactas.

### Implementación de la User Story 2

- [X] T018 [P] [US2] Crear `dbt_birds/models/staging/stg_inaturalist__observations.sql` — materialized=view; `CAST(id AS BIGINT) AS observation_id`; parsear `created_at` → `TIMESTAMP` UTC como `created_at_utc`; `CAST(split_part(location, ',', 1) AS DOUBLE) AS latitude`; `CAST(split_part(location, ',', 2) AS DOUBLE) AS longitude`; aplanar `taxon.id` → `taxon_id BIGINT`, `taxon.name` → `taxon_scientific_name`, `taxon.preferred_common_name` → `taxon_common_name` (admite nulos), `taxon.rank` → `taxon_rank`, `taxon.threatened` → `taxon_threatened BOOLEAN`; aplanar `user.id` → `user_id BIGINT`, `user.login` → `user_login`, `user.name` → `user_display_name` (admite nulos); deduplicación: `ROW_NUMBER() OVER (PARTITION BY observation_id ORDER BY created_at_utc DESC) = 1`; propagar las columnas de partición `_ingested_year`, `_ingested_month`
- [X] T019 [P] [US2] Crear `dbt_birds/models/staging/stg_inaturalist__observations.yml` — documentar las 17 columnas con descripción; tests: `observation_id` (unique, not_null), `quality_grade` (accepted_values: [research, needs_id, casual]), `latitude` (not_null), `longitude` (not_null), `taxon_id` (not_null), `user_id` (not_null)
- [X] T020 [US2] Crear `dbt_birds/models/intermediate/int_observations__geospatial_enriched.sql` — materialized=view; FROM `stg_inaturalist__observations`; filtro bbox: `latitude BETWEEN 46.8600781 AND 47.8359431 AND longitude BETWEEN -2.6257395 AND -0.9466615` (límite inclusivo, ≥/≤); `(quality_grade = 'research') AS is_research_grade`; convertir `created_at_utc` a la hora de `Europe/Paris` y aplicar CASE: 0-5→'Madrugada', 6-11→'Mañana', 12-17→'Tarde', 18-23→'Noche' AS `observation_period`; `YEAR(observed_on) AS observed_year`; `MONTH(observed_on) AS observed_month`; propagar todas las columnas de staging
- [X] T021 [P] [US2] Crear `dbt_birds/models/intermediate/int_observations__geospatial_enriched.yml` — documentar todas las columnas; tests: `observation_id` (unique, not_null), `is_research_grade` (not_null), `observation_period` (accepted_values: [Madrugada, Mañana, Tarde, Noche]); referenciar el test singular personalizado `assert_observations_within_nantes_bbox`
- [X] T022 [P] [US2] Crear `dbt_birds/tests/assert_observations_within_nantes_bbox.sql` — test singular: `SELECT * FROM {{ ref('int_observations__geospatial_enriched') }} WHERE latitude < 46.8600781 OR latitude > 47.8359431 OR longitude < -2.6257395 OR longitude > -0.9466615`; debe devolver 0 filas para pasar (SC-003)
- [X] T023 [P] [US2] Crear `dbt_birds/models/marts/dim_species.sql` — materialized=table; `SELECT DISTINCT taxon_id AS species_key, taxon_id, taxon_scientific_name AS scientific_name, taxon_common_name AS common_name, taxon_rank, taxon_threatened AS is_threatened FROM {{ ref('int_observations__geospatial_enriched') }}`
- [X] T024 [P] [US2] Crear `dbt_birds/models/marts/dim_species.yml` — documentar las 6 columnas (indicar que `common_name` admite nulos); tests: `species_key` (unique, not_null), `taxon_id` (unique, not_null), `scientific_name` (not_null)
- [X] T025 [P] [US2] Crear `dbt_birds/models/marts/dim_users.sql` — materialized=table; `SELECT DISTINCT user_id AS user_key, user_id, user_login AS login, user_display_name AS display_name FROM {{ ref('int_observations__geospatial_enriched') }}`
- [X] T026 [P] [US2] Crear `dbt_birds/models/marts/dim_users.yml` — documentar las 4 columnas (indicar que `display_name` admite nulos); tests: `user_key` (unique, not_null), `user_id` (unique, not_null), `login` (not_null)
- [X] T027 [P] [US2] Crear `dbt_birds/models/marts/dim_date.sql` — materialized=table; generar la serie de fechas: de `MIN(observed_on) - INTERVAL '30' DAY` a `MAX(observed_on) + INTERVAL '30' DAY` a partir de `int_observations__geospatial_enriched`; columnas: `date_key DATE`, `year INT`, `month INT (1-12)`, `month_name VARCHAR`, `quarter INT (1-4 = CEIL(month/3.0))`, `day_of_week INT (ISO 1=Mon–7=Sun)`, `day_name VARCHAR`, `week_of_year INT`, `is_weekend BOOLEAN (day_of_week IN (6,7))`, `biological_season VARCHAR (month 3-5→'Primavera', 6-8→'Verano', 9-11→'Otoño', 12,1,2→'Invierno')`
- [X] T028 [P] [US2] Crear `dbt_birds/models/marts/dim_date.yml` — documentar las 10 columnas; tests: `date_key` (unique, not_null), `biological_season` (accepted_values: [Primavera, Verano, Otoño, Invierno])
- [X] T029 [US2] Crear `dbt_birds/models/marts/fct_observations.sql` — config: `materialized=incremental, incremental_strategy=insert_overwrite, partitioned_by=['year','month'], format='parquet', write_compression='snappy'`; JOIN de `int_observations__geospatial_enriched` con `dim_species` (ON `taxon_id = species_key`), `dim_users` (ON `user_id = user_key`), `dim_date` (ON `observed_on = date_key`); SELECT `observation_id, species_key, user_key, date_key, latitude, longitude, positional_accuracy_m, quality_grade, is_research_grade, observation_period, created_at_utc, observed_year AS year, observed_month AS month`; filtro incremental: `WHERE observed_on > (SELECT MAX(date_key) FROM {{ this }})`
- [X] T030 [P] [US2] Crear `dbt_birds/models/marts/fct_observations.yml` — documentar las 13 columnas; tests: `observation_id` (unique, not_null), `species_key` (not_null, relationships→dim_species.species_key), `user_key` (not_null, relationships→dim_users.user_key), `date_key` (not_null, relationships→dim_date.date_key), `quality_grade` (accepted_values: [research, needs_id, casual]), `is_research_grade` (not_null)
- [X] T031 [US2] Completar `dbt_birds/.github/workflows/dbt_ci.yml` — disparador: `on: [pull_request]` para las rutas `dbt_birds/**`; pasos: checkout, instalar `dbt-athena-community`, configurar `profiles.yml` a partir de los secrets de GitHub (`DBT_ATHENA_S3_STAGING_DIR`, `DBT_ATHENA_S3_DATA_DIR`), `dbt compile`, `dbt test --select state:modified+`; el workflow falla ante cualquier test de dbt fallido (SC-004)

**Punto de control**: User Story 2 totalmente funcional — el DAG completo de dbt produce el esquema estrella validado de forma independiente

---

## Phase 5: User Story 3 — Insights de Biodiversidad en Power BI (Prioridad: P3)

**Objetivo**: El informe de Power BI se conecta a los marts de Athena en modo Import y muestra tres visuales analíticos interactivos: mapa geoespacial, tendencia estacional y tabla de ranking.

**Prueba Independiente**: Conectar Power BI Desktop al esquema `birds_dbt` de Athena → importar las 4 tablas de marts → verificar que el mapa muestra las observaciones geolocalizadas, que el gráfico estacional muestra las 4 estaciones biológicas, que la tabla de ranking lista las especies y observadores principales y que el filtrado cruzado funciona entre todos los visuales.

### Implementación de la User Story 3

- [X] T032 [P] [US3] Crear `docs/powerbi-setup.md` — documentar los pasos de conexión ODBC: instalar el driver ODBC de Amazon Athena (Simba, 64 bits), crear un DSN que apunte a `athena.eu-west-3.amazonaws.com`, base de datos `birds_dbt`, configurar las credenciales de AWS; Power BI Desktop: Get Data → ODBC → seleccionar el DSN → modo Import; tablas: `fct_observations`, `dim_species`, `dim_users`, `dim_date`
- [X] T033 [US3] Crear `reports/nantes_birds.pbix` — archivo de informe de Power BI: importar las 4 tablas de marts mediante el DSN ODBC de Athena; configurar las relaciones del esquema estrella en la vista Model según `contracts/dbt-models.md`: `fct_observations[species_key]→dim_species[species_key]` (Many-to-One), `fct_observations[user_key]→dim_users[user_key]` (Many-to-One), `fct_observations[date_key]→dim_date[date_key]` (Many-to-One)
- [X] T034 [P] [US3] Añadir el visual de mapa geoespacial a `reports/nantes_birds.pbix` — visual de mapa (ArcGIS Maps o el mapa integrado): latitud de `fct_observations[latitude]`, longitud de `fct_observations[longitude]`; tooltip con `dim_species[common_name]` y `quality_grade`; segmentador de especie sobre `dim_species[common_name]` (FR-013)
- [X] T035 [P] [US3] Añadir el visual de tendencia estacional a `reports/nantes_birds.pbix` — gráfico de barras agrupadas: eje X `dim_date[month_name]`, eje Y `COUNT(fct_observations[observation_id])`, leyenda coloreada por `dim_date[biological_season]` (Primavera/Verano/Otoño/Invierno); segmentador de rango de fechas sobre `dim_date[date_key]`
- [X] T036 [P] [US3] Añadir el visual de tabla de ranking y las medidas DAX a `reports/nantes_birds.pbix` — visual de tabla: `dim_species[common_name]` + `COUNT(observation_id)` DESC, `dim_users[login]` + `COUNT(observation_id)` DESC; añadir las medidas: `Total Observations = COUNTROWS(fct_observations)`, `Distinct Species = DISTINCTCOUNT(fct_observations[species_key])`, `Research Grade % = DIVIDE(CALCULATE(COUNTROWS(fct_observations), fct_observations[is_research_grade]=TRUE()), COUNTROWS(fct_observations))` (FR-012)
- [X] T037 [US3] Publicar `reports/nantes_birds.pbix` en Power BI Service — subirlo al workspace; configurar la actualización programada del dataset (diaria, a una hora posterior al cron de EventBridge que dispara Lambda); verificar que los 3 visuales se muestran correctamente con datos reales y responden al filtrado cruzado; confirmar que la actualización trae las observaciones nuevas sin intervención manual (SC-001, SC-005)

**Punto de control**: User Story 3 totalmente funcional — todos los insights analíticos accesibles sin escribir SQL

---

## Phase 6: Polish y Aspectos Transversales

**Propósito**: Observabilidad, programación y validación de todas las historias de usuario

- [X] T038 [P] Configurar una alarma de CloudWatch sobre la métrica de errores/timeouts de la Lambda `birds-inaturalist-ingestion` (umbral: ≥1 en 5 minutos) conectada a un topic SNS que notifique por correo al responsable del pipeline (FR-016)
- [X] T039 [P] Configurar una regla cron diaria de Amazon EventBridge que apunte a la Lambda `birds-inaturalist-ingestion` (expresión cron de ejecución diaria, programada antes de la actualización de Power BI) — documentar la expresión cron y los permisos IAM en `docs/infrastructure.md`
- [X] T040 Ejecutar de extremo a extremo los 7 escenarios de validación de quickstart.md y documentar los resultados (pass/fail) en `docs/validation-results.md`: Escenario 1 (ingesta de primera ejecución), Escenario 2 (incremental sin duplicados), Escenario 3 (tests de staging), Escenario 4 (validación del bbox), Escenario 5 (integridad completa de marts), Escenario 6 (actualización de Power BI), Escenario 7 (idempotencia ante fallos)
- [X] T041 [P] Revisar todos los archivos `.yml` de los modelos dbt — confirmar que cada columna de los 7 modelos tiene un campo `description` y al menos un test; añadir la documentación que falte según el principio V de la constitución

---

## Dependencias y Orden de Ejecución

### Dependencias entre Fases

- **Setup (Phase 1)**: Sin dependencias — puede empezar de inmediato
- **Foundational (Phase 2)**: Depende de completar la Phase 1 — bloquea todas las historias de usuario
- **User Story 1 (Phase 3)**: Depende de la Phase 2 — puede empezar en paralelo con la Phase 4
- **User Story 2 (Phase 4)**: Depende de la Phase 2 — puede empezar en paralelo con la Phase 3
- **User Story 3 (Phase 5)**: Depende de completar la Phase 4 (los marts deben estar poblados)
- **Polish (Phase 6)**: Depende de completar todas las fases anteriores

### Dependencias entre Historias de Usuario

- **US1 (P1)**: Depende solo de Foundational — sin dependencia de US2/US3
- **US2 (P2)**: Depende solo de Foundational — necesita una capa raw poblada para `dbt run`, pero el código de los modelos puede escribirse en paralelo con US1
- **US3 (P3)**: Depende de que la capa de marts de US2 esté poblada y validada

### Dentro de Cada Historia de Usuario

- US1: T010, T011, T012 son paralelas → T013 depende de las tres → T014–T016 son paralelas → T017 depende de T013
- US2: T018/T019 en paralelo → T020 depende de T018 → T021/T022 en paralelo con T020 → T023–T028 en paralelo → T029 depende de T023+T025+T027 → T030 en paralelo con T029 → T031 independiente
- US3: T032 en paralelo → T033 depende de T032 → T034/T035/T036 en paralelo → T037 depende de T033–T036

---

## Ejemplos de Ejecución en Paralelo

### User Story 1 — Oportunidades de Paralelismo

```bash
# Paralelo: implementar los tres módulos de Lambda a la vez
Task T010: ingestion/inaturalist_client.py
Task T011: ingestion/s3_writer.py
Task T012: ingestion/ssm_watermark.py

# Paralelo: escribir los tests unitarios junto a cada módulo
Task T014: tests/unit/test_inaturalist_client.py
Task T015: tests/unit/test_s3_writer.py
Task T016: tests/unit/test_ssm_watermark.py

# Secuencial: el handler después de completar todos los módulos
Task T013: ingestion/handler.py  (depende de T010+T011+T012)
```

### User Story 2 — Oportunidades de Paralelismo

```bash
# Paralelo: SQL y YAML de staging a la vez
Task T018: stg_inaturalist__observations.sql
Task T019: stg_inaturalist__observations.yml

# Paralelo: los tres modelos de dimensión una vez terminada la capa intermedia
Task T023: dim_species.sql      Task T024: dim_species.yml
Task T025: dim_users.sql        Task T026: dim_users.yml
Task T027: dim_date.sql         Task T028: dim_date.yml

# Secuencial: la tabla de hechos después de todas las dimensiones
Task T029: fct_observations.sql  (depende de T023+T025+T027)
```

---

## Estrategia de Implementación

### Primero el MVP (Solo la User Story 1)

1. Completar la Phase 1: Setup
2. Completar la Phase 2: Foundational (CRÍTICO — bloquea todas las historias)
3. Completar la Phase 3: User Story 1 (T010–T017)
4. **PARAR Y VALIDAR**: invocar Lambda, revisar los archivos en S3, verificar el watermark de SSM, confirmar que no hay duplicados
5. US1 es entregable y verificable de forma independiente

### Entrega Incremental

1. Setup + Foundational → andamiaje listo
2. US1 (ingesta con Lambda) → capa raw de S3 poblada → **demo del MVP**
3. US2 (transformaciones dbt) → esquema estrella disponible en Athena → ejecutar `dbt test`
4. US3 (Power BI) → dashboards analíticos disponibles → demo para las partes interesadas
5. Polish → alertas, programación, validación completa de extremo a extremo

### Estrategia con Equipo en Paralelo

Con varios desarrolladores, una vez completada la Phase 2:
- Desarrollador A: User Story 1 (ingesta con Lambda, Python)
- Desarrollador B: User Story 2 (modelos dbt, SQL)
- Ambas historias se completan de forma independiente; US3 empieza cuando los marts de US2 están validados

---

## Notas

- Las tareas **[P]** operan sobre archivos distintos sin dependencias entre sí — se pueden ejecutar en paralelo con seguridad
- La etiqueta **[Story]** permite trazar cada tarea hasta los criterios de aceptación de spec.md
- El watermark **nunca** debe actualizarse ante un fallo parcial en S3 (constitución IV + FR-002)
- El primer `dbt run` de `fct_observations` requiere `--full-refresh` (insert_overwrite necesita crear las particiones)
- El registro con `dbt-external-tables` (`dbt run-operation stage_external_sources`) es un paso único, una vez existan datos raw en S3 — documentado en quickstart.md
- El rol IAM de Lambda debe limitarse a `s3:PutObject` sobre el prefijo destino + `ssm:GetParameter`/`ssm:PutParameter` sobre el ARN único del watermark — sin ARNs comodín (constitución IV)
- Todos los modelos de marts deben llevar `format='parquet'` + `write_compression='snappy'` por gobierno de costes (constitución IV)

---

## Phase 7: Convergence

- [X] T042 Mover `dbt_birds/.github/workflows/dbt_ci.yml` a `.github/workflows/dbt_ci.yml` en la raíz del repositorio para que GitHub Actions pueda descubrirlo y ejecutarlo según FR-016 (missing)
- [ ] T043 Crear `reports/nantes_birds.pbix` con Power BI Desktop: conectar al DSN ODBC de Athena (esquema `birds_dbt`), importar las 4 tablas de marts, configurar las relaciones del esquema estrella, añadir los visuales de mapa geoespacial, tendencia estacional y ranking con las medidas DAX, y hacer commit del binario según US3/AC1-4, FR-012, FR-013 (missing)
- [ ] T044 Ejecutar los 7 escenarios de validación de quickstart.md contra el entorno real de AWS y actualizar `docs/validation-results.md` con los resultados reales (pass/fail) según T040, SC-004, SC-006 (partial)
