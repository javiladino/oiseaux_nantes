# Resultados de Validación — Pipeline de Aves de Nantes

**Referencia**: `specs/001-nantes-birds-pipeline/quickstart.md`

---

## Resultados de los Tests Unitarios (Sin AWS Real)

Ejecutados con `PYTHONPATH=ingestion pytest tests/unit/ -v`:

| Módulo | Tests | Resultado |
|--------|-------|-----------|
| `test_inaturalist_client.py` | 6 | ✅ PASS |
| `test_s3_writer.py` | 4 | ✅ PASS |
| `test_ssm_watermark.py` | 4 | ✅ PASS |
| **Total** | **14** | **✅ 14/14 PASS** |

---

## Estado de los Escenarios End-to-End (Requieren AWS Real)

| Escenario | Descripción | Estado | Notas |
|-----------|-------------|--------|-------|
| 1 | Ingesta de primera ejecución | PENDIENTE | Requiere Lambda + S3 + SSM reales |
| 2 | Ejecución incremental — sin duplicados | PENDIENTE | Requiere la línea base del Escenario 1 |
| 3 | Validación del modelo de staging en dbt | PENDIENTE | Requiere datos raw en S3 + Athena |
| 4 | Validación del bbox en la capa intermedia | PENDIENTE | Requiere la línea base del Escenario 3 |
| 5 | Integridad completa del esquema estrella en marts | PENDIENTE | Requiere la línea base del Escenario 4 |
| 6 | Actualización end-to-end en Power BI | PENDIENTE | Requiere el Escenario 5 + Power BI Desktop |
| 7 | Idempotencia ante fallos | PENDIENTE | Requiere completar los Escenarios 1–2 |

---

## Cómo Ejecutar la Validación End-to-End

Ver `specs/001-nantes-birds-pipeline/quickstart.md` para los comandos paso a paso de cada escenario.

Requisitos previos:
- AWS CLI configurado para `eu-west-3`
- Lambda `birds-inaturalist-ingestion` desplegada con la variable de entorno `BIRDS_S3_BUCKET`
- Bucket S3 con el prefijo `raw/inaturalist/`
- Parámetro SSM `/birds-pipeline/last_successful_run_date` (ausente = primera ejecución)
- Workgroup de Athena + bases de datos de Glue (`birds_raw`, `birds_dbt`) creados
- Proyecto dbt instalado: `pip install dbt-athena-community && cd dbt_birds && dbt deps`
- Para el Escenario 6: Power BI Desktop con el driver ODBC de Amazon Athena

Actualizar la tabla anterior con los resultados (pass/fail) a medida que cada escenario se valide en el entorno real.
