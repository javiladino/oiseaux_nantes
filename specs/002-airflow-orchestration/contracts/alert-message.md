# Contrato: Mensaje de Alerta

**Productor**: `orchestration/plugins/alerts.py` (callbacks de Airflow)
**Canal**: topic SNS `birds-pipeline-alerts` → suscripción por email (feature 001)
**Fecha**: 2026-10-11

---

## Cuándo se envía

| Tipo | Disparador | Requisito |
|------|------------|-----------|
| `task_failure` | Una tarea pasa a `failed` tras agotar sus reintentos | FR-008, SC-003 |
| `deadline_missed` | La ejecución programada no ha terminado a las 07:00 UTC | SC-001, caso límite |

No se envía alerta en los reintentos intermedios (`up_for_retry`) ni para las tareas en
`upstream_failed`: solo la tarea que falló origina el aviso.

## Asunto (SNS `Subject`, máx. 100 caracteres)

```
[birds-pipeline] FALLO <task_id> (<logical_date YYYY-MM-DD>)
[birds-pipeline] RETRASO nantes_birds_pipeline (<logical_date YYYY-MM-DD>)
```

## Cuerpo (SNS `Message`, JSON)

```json
{
  "type": "task_failure",
  "dag_id": "nantes_birds_pipeline",
  "run_id": "scheduled__2026-10-12T05:00:00+00:00",
  "logical_date": "2026-10-12T05:00:00+00:00",
  "task_id": "dbt_medallion.int_observations__geospatial_enriched.test",
  "try_number": 3,
  "error": "Failure in test assert_observations_within_nantes_bbox ...",
  "log_url": "http://localhost:8080/dags/nantes_birds_pipeline/runs/.../tasks/...",
  "hint": "Abrir la UI con Session Manager (ver docs/airflow-operations.md)"
}
```

| Campo | Obligatorio | Notas |
|-------|-------------|-------|
| `type` | Sí | `task_failure` \| `deadline_missed` |
| `dag_id`, `run_id`, `logical_date` | Sí | |
| `task_id`, `try_number` | Solo `task_failure` | |
| `error` | Solo `task_failure` | Truncado a 1.000 caracteres; sin secretos |
| `log_url` | Sí | Apunta a `localhost:8080`, accesible tras abrir el túnel de Session Manager |
| `hint` | Sí | Texto fijo con el siguiente paso |

## Fallos al alertar

Si la publicación en SNS falla, el callback registra el error en el log de la tarea y **no**
cambia el estado de la ejecución. La alarma de CloudWatch sobre la Lambda sigue siendo un
respaldo independiente para los fallos de ingesta.
