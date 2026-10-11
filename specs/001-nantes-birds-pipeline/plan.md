# Plan de Implementación: Pipeline de Biodiversidad de Aves en Nantes

**Rama**: `001-nantes-birds-pipeline` | **Fecha**: 2026-10-10 | **Spec**: [spec.md](spec.md)

**Entrada**: Especificación del feature en `/specs/001-nantes-birds-pipeline/spec.md`

## Resumen

Pipeline ELT end-to-end que ingesta observaciones de aves desde la API pública de iNaturalist
para el área del Gran Nantes, persiste el JSON crudo en S3 y lo transforma mediante una
arquitectura medallón dbt de tres capas (staging → intermedia → marts) sobre AWS Athena hasta
obtener un modelo dimensional en esquema estrella consumido por Power BI. La ingesta es
incremental, con watermark en SSM Parameter Store, y se orquesta diariamente con EventBridge.

## Contexto Técnico

**Lenguaje/Versión**: Python 3.11+ (ingesta en Lambda), SQL (modelos dbt)

**Dependencias Principales**:
- `requests` — cliente HTTP de la API de iNaturalist en Lambda
- `boto3` — escritura en S3 y lectura/escritura del watermark en SSM
- `dbt-core` + `dbt-athena-community` — capa de transformación medallón
- `pytest` + `moto` — tests unitarios de Lambda con AWS simulado

**Almacenamiento**:
- AWS S3 — zona raw (`raw/inaturalist/observations/year=YYYY/month=MM/`) y zona procesada
  (Parquet, gestionada por dbt-athena)
- AWS Glue Data Catalog — registro de esquemas de todas las tablas/vistas de Athena
- AWS Athena — motor SQL serverless que ejecuta todas las transformaciones dbt
- AWS SSM Parameter Store — un único parámetro `String` que persiste el watermark de ingesta

**Pruebas**:
- Lambda: `pytest` con `moto` para simular S3/SSM; test de integración contra la API real de
  iNaturalist (solo lectura, sin efectos secundarios)
- dbt: tests de esquema integrados (`unique`, `not_null`, `accepted_values`, `relationships`);
  tests singulares personalizados para la contención en el bounding box

**Plataforma Objetivo**: AWS (Lambda + EventBridge para la programación, S3 + Glue + Athena para
el lake, SSM para la configuración, CloudWatch + SNS para las alertas); Power BI Desktop /
Service para el consumo

**Tipo de Proyecto**: Pipeline de datos ELT + proyecto de analytics engineering

**Objetivos de Rendimiento**:
- La ingesta respeta el rate limit de iNaturalist (~1 req/s)
- La ejecución de Lambda (en frío y en caliente) termina dentro del límite estricto de 3 minutos
  para el volumen diario típico
- Las consultas de Athena usan partition pruning; coste de escaneo por consulta cercano a cero

**Restricciones**:
- Timeout de Lambda ≤ 3 minutos (constitución IV)
- Archivos raw almacenados como JSON (sin transformación en la ingesta); archivos procesados
  como Parquet + Snappy
- Rol IAM de Lambda: `s3:PutObject` sobre el prefijo destino + `ssm:GetParameter`/`ssm:PutParameter`
  sobre el ARN único del watermark + `logs:CreateLogGroup`/`logs:PutLogEvents`; sin ARNs comodín
- El watermark se actualiza atómicamente solo después de una escritura exitosa en S3; nunca se
  actualiza ante un fallo parcial

**Escala/Alcance**:
- Volumen diario esperado: cientos de observaciones para el bounding box de Nantes
- Esquema estrella: 1 tabla de hechos + 3 tablas de dimensiones; `dim_date` cubre el rango
  completo de fechas observadas
- Power BI en modo Import, actualización programada diaria alineada con la cadencia de ingesta

## Constitution Check

*PUERTA: Debe superarse antes de la investigación de la Fase 0. Se vuelve a verificar tras el
diseño de la Fase 1.*

| Principio | Puerta | Estado | Notas |
|-----------|--------|--------|-------|
| I. Separación ELT | Lambda hace solo EL; dbt hace T; Power BI lee solo marts | **PASS** | Sin lógica de transformación en Lambda |
| II. API Ética | Incremental, ~1 req/s, cabecera `User-Agent` identificable | **PASS** | La re-ingesta completa queda tras un disparo manual según la spec |
| III. DQ Cero Fallos | Tests dbt: unicidad de PK, límites geográficos, valores de `quality_grade` | **PASS** | FR-008/010/015; SC-004 bloquea la promoción ante cualquier fallo de test |
| IV. Mínimo Privilegio | IAM restringido a un prefijo S3 + un ARN SSM; Lambda ≤3 min; Parquet+Snappy | **PASS** | FR-002 restringe explícitamente el IAM de SSM |
| V. Idempotencia y Docs | Deduplicación por `observation_id`; cada modelo tiene docs + tests en `.yml` | **PASS** | FR-014/015 |

**Sin violaciones. Se procede a la Fase 0.**

## Estructura del Proyecto

### Documentación (este feature)

```text
specs/001-nantes-birds-pipeline/
├── plan.md              # Este archivo
├── research.md          # Salida de la Fase 0
├── data-model.md        # Salida de la Fase 1
├── quickstart.md        # Salida de la Fase 1
├── contracts/           # Salida de la Fase 1
│   ├── inaturalist-api.md
│   └── dbt-models.md
└── tasks.md             # Salida de la Fase 2 (/speckit-tasks — NO lo crea /speckit-plan)
```

### Código Fuente (raíz del repositorio)

```text
ingestion/                          # Paquete Lambda (Python 3.11+)
├── handler.py                      # Punto de entrada de Lambda; orquesta fetch → write → watermark
├── inaturalist_client.py           # Cliente HTTP: GET /v1/observations paginado, rate limiting
├── s3_writer.py                    # Escribe lotes de JSON crudo en S3 con la clave de partición correcta
├── ssm_watermark.py                # get/put atómico en SSM del watermark incremental
└── requirements.txt                # requests, boto3

tests/
├── unit/
│   ├── test_inaturalist_client.py
│   ├── test_s3_writer.py
│   └── test_ssm_watermark.py
└── integration/
    └── test_ingestion_e2e.py       # API real de iNaturalist + localstack o AWS real

dbt_birds/                          # Raíz del proyecto dbt
├── dbt_project.yml
├── profiles.yml                    # Conexión a Athena (s3_staging_dir, región, catálogo)
├── models/
│   ├── sources/
│   │   └── sources.yml             # Definición de la tabla externa raw_inaturalist
│   ├── staging/
│   │   ├── stg_inaturalist__observations.sql
│   │   └── stg_inaturalist__observations.yml
│   ├── intermediate/
│   │   ├── int_observations__geospatial_enriched.sql
│   │   └── int_observations__geospatial_enriched.yml
│   └── marts/
│       ├── fct_observations.sql
│       ├── fct_observations.yml
│       ├── dim_species.sql
│       ├── dim_species.yml
│       ├── dim_users.sql
│       ├── dim_users.yml
│       ├── dim_date.sql
│       └── dim_date.yml
└── tests/
    └── assert_observations_within_nantes_bbox.sql

.github/
└── workflows/
    └── dbt_ci.yml                  # dbt test en cada PR; el workflow falla ante cualquier test fallido
```

**Decisión de Estructura**: Repositorio único con `ingestion/` (Lambda en Python) y
`dbt_birds/` (proyecto dbt) como directorios hermanos de primer nivel. La infraestructura
(Terraform) queda explícitamente fuera del alcance según los supuestos de la spec. La CI de
GitHub Actions vive en `.github/workflows/`.

## Seguimiento de Complejidad

> No se detectaron violaciones de la constitución. Esta sección está vacía intencionadamente.
