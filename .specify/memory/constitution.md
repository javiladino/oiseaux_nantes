<!--
## Sync Impact Report
Generado: 2026-10-10
---
Cambio de versión: [sin versión / plantilla vacía] → 1.0.0 (MAJOR — ratificación inicial)

Secciones añadidas:
  - Visión y Propósito del Proyecto (preámbulo, antes de los Principios Fundamentales)
  - Principios Fundamentales (5 principios — todos nuevos):
      I.   Separación de Responsabilidades ELT
      II.  Ingesta Ética de la API y Rate Limiting
      III. Calidad de Datos con Cero Fallos (NO NEGOCIABLE)
      IV.  Seguridad de Mínimo Privilegio y Gobierno de Costes
      V.   Idempotencia y Documentación
  - Stack Tecnológico y Roles (Sección 2 — nueva)
  - Estándares de Modelado Medallón en dbt (Sección 3 — nueva)
  - Gobernanza (nueva)

Principios modificados: N/A (ratificación inicial)
Secciones eliminadas: N/A

TODOs aplazados:
  - RATIFICATION_DATE fijada en 2026-10-10 (hoy). Actualizar si el proyecto empezó antes.

Este comentario es material de trabajo para revisión humana. Eliminar antes de hacer commit.
-->

# Constitución del Pipeline Analítico de Biodiversidad en Nantes

## Visión y Propósito del Proyecto

Construir un pipeline Modern Data Stack (MDS) end-to-end, escalable, robusto y eficiente en
costes para ingestar, limpiar, modelar y visualizar observaciones de fauna de ciencia ciudadana
(en concreto Aves en Nantes, Francia) procedentes de la plataforma de código abierto iNaturalist.

Este pipeline sirve como proyecto analítico de referencia que demuestra buenas prácticas de Data
Engineering de nivel senior: EL Serverless (Extract & Load), Analytics Engineering con dbt y
Business Intelligence con Power BI.

## Principios Fundamentales

### I. Separación de Responsabilidades ELT

**Ingesta (EL):** AWS Lambda es la única responsable de la extracción de datos y de su
persistencia en almacenamiento de objetos (AWS S3). Lambda NO DEBE realizar transformaciones
analíticas pesadas.

**Almacenamiento (Data Lake):** S3 es la única fuente de verdad. Los datos raw DEBEN
particionarse temporalmente (`raw/dataset/year=YYYY/month=MM/`).

**Transformación (T):** Todas las transformaciones analíticas DEBEN ejecutarse con dbt mediante
SQL in-place sobre AWS Athena. Sin procesamiento fila a fila en Lambda.

**Serving y BI:** Power BI DEBE consumir únicamente data marts modelados y curados (`marts/`).
Queda prohibido el acceso directo a las capas raw o de staging.

*Justificación: Mantener separadas con claridad la ingesta, el almacenamiento, la transformación
y el serving permite escalar, probar y auditar cada capa de forma independiente.*

### II. Ingesta Ética de la API y Rate Limiting

La ingesta DEBE respetar estrictamente los rate limits de la API de iNaturalist (~1 petición
por segundo).

Todas las llamadas a la API DEBEN incluir una cabecera `User-Agent` identificable que
identifique este proyecto.

La ingesta DEBE ejecutarse de forma incremental, capturando solo los registros recién creados
o recién observados desde la última ejecución exitosa. Una re-ingesta completa DEBE estar
justificada explícitamente y quedar tras un disparo manual.

*Justificación: Un uso responsable de la API pública de iNaturalist protege el servicio de
origen y el acceso continuado del proyecto a los datos.*

### III. Calidad de Datos con Cero Fallos (NO NEGOCIABLE)

El JSON raw DEBE almacenarse exactamente como se recibe (tolerante al schema drift en la capa raw).

Antes de la promoción a los marts de producción, los tests de dbt DEBEN garantizar:
- `observation_id` es único y no nulo (integridad de la clave primaria).
- La latitud y la longitud están dentro del bounding box del Gran Nantes.
- Los valores de `quality_grade` coinciden con la taxonomía de iNaturalist: `research`,
  `needs_id` o `casual`.

Un modelo dbt NO DEBE fusionarse en `main` si falla cualquier test de esquema.

*Justificación: Los dashboards de Power BI y las consultas analíticas posteriores dependen de
datos fiables. Una corrupción silenciosa de datos es peor que un fallo visible del pipeline.*

### IV. Seguridad de Mínimo Privilegio y Gobierno de Costes

**IAM:** Los roles de ejecución de Lambda DEBEN tener solo `s3:PutObject` sobre el prefijo S3
destino y permisos de escritura en CloudWatch Logs. No se permiten ARNs de recurso comodín.

**Lambda:** El timeout de la función DEBE limitarse a 3 minutos.

**Athena:** Todos los datos procesados DEBEN almacenarse como Parquet con compresión Snappy. Las
consultas DEBEN usar partition pruning (predicados sobre `year`, `month`) para mantener el coste
de escaneo por consulta cercano a cero.

*Justificación: El proyecto apunta a un coste operativo cercano a cero. Los roles IAM
sobredimensionados amplían innecesariamente la superficie de impacto en seguridad; los escaneos
de Athena no optimizados son el principal generador de costes.*

### V. Idempotencia y Documentación

**Idempotencia:** Cualquier ejecución de la Lambda de ingesta o de dbt DEBE producir el mismo
estado final sin importar cuántas veces se re-ejecute. La deduplicación DEBE basarse en
`observation_id`.

**Documentación:** Cada modelo dbt y cada columna DEBEN documentarse en su archivo `.yml`
asociado con al menos un test de dbt. Un PR que añada o modifique un modelo sin actualizar su
`.yml` NO DEBE fusionarse en `main`.

*Justificación: La idempotencia permite reintentar el pipeline tras un fallo sin limpieza
manual. La documentación obligatoria garantiza que el proyecto siga siendo legible como
implementación de referencia.*

## Stack Tecnológico y Roles

| Capa | Tecnología | Función Principal |
| :--- | :--- | :--- |
| **Motor de Ingesta** | AWS Lambda (Python 3.11+) | Consumidor incremental serverless de la API |
| **Programador** | Amazon EventBridge | Orquestación cron de la ingesta periódica |
| **Almacenamiento / Lake** | AWS S3 | Zona raw (JSON) y zona procesada (Parquet) |
| **Catálogo y Esquema** | AWS Glue Data Catalog | Crawler de metadatos y definiciones de tablas |
| **Motor de Cómputo** | AWS Athena | Motor SQL distribuido serverless |
| **Transformación** | dbt-core / dbt-athena | Linaje, modelado, tests, documentación |
| **Visualización** | Power BI Desktop / Service | Dashboards, mapas geoespaciales, tendencias taxonómicas |
| **IaC y CI/CD** | Terraform y GitHub Actions | Infraestructura reproducible, tests dbt automatizados |

Cualquier cambio en el stack tecnológico DEBE registrarse como enmienda de la constitución
(como mínimo incremento MINOR) antes de empezar la implementación.

## Estándares de Modelado Medallón en dbt

Todos los modelos dbt DEBEN seguir la siguiente arquitectura medallón de tres capas:

```
raw_inaturalist (S3 / Athena External Table)
       │
       ▼
stg_inaturalist__observations.sql
  (Staging: cast types, rename columns, flatten JSON, preliminary dedup)
       │
       ▼
int_observations__geospatial_enriched.sql
  (Intermediate: spatial validation, date logic, daylight period categorization)
       │
       ├───────────────────────────────────┐
       ▼                                   ▼
fct_observations.sql               dim_species.sql
  (Marts: star schema for Power BI analytical querying)
```

**Staging (`stg_`):** Mapeo 1:1 con la fuente raw. Solo casteo de tipos, nombres de columna
uniformes en snake_case y deduplicación preliminar. No se permite lógica de negocio.

**Intermedia (`int_`):** Joins entre modelos de staging y lógica de negocio (p. ej.,
clasificación de las horas de observación en franjas del día, enriquecimiento espacial). Sin
referencias directas a la fuente raw.

**Marts (`fct_`, `dim_`):** Esquema estrella dimensional optimizado para consultas rápidas desde
Power BI. Power BI DEBE referenciar únicamente esta capa.

Saltarse una capa (p. ej., de staging directamente a marts) está prohibido sin una enmienda
explícita de la constitución.

## Gobernanza

Esta constitución prevalece sobre cualquier otra práctica o convención del proyecto. En caso de
conflicto entre este documento y cualquier otra directriz, prevalece este documento.

**Procedimiento de Enmienda:**
1. Abrir un PR que modifique `.specify/memory/constitution.md`.
2. Incrementar la versión siguiendo el versionado semántico:
   - **MAJOR:** Eliminación o redefinición incompatible de un principio existente.
   - **MINOR:** Nuevo principio, nueva sección o ampliación sustancial de las directrices.
   - **PATCH:** Aclaraciones, correcciones de redacción, refinamientos no semánticos.
3. La descripción del PR DEBE explicar la justificación de la enmienda.
4. Al menos un revisor DEBE aprobarlo antes del merge en `main`.

**Cumplimiento:** Todos los PRs DEBEN revisarse para verificar el cumplimiento de esta
constitución antes del merge. Cualquier complejidad añadida más allá de lo que requiere un
feature DEBE justificarse explícitamente frente a los principios anteriores.

**Version**: 1.0.0 | **Ratified**: 2026-10-10 | **Last Amended**: 2026-10-10
