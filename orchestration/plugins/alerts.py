"""Alertas del DAG nantes_birds_pipeline hacia el topic SNS birds-pipeline-alerts.

Contrato: specs/002-airflow-orchestration/contracts/alert-message.md
- task_failure: una tarea falla tras agotar sus reintentos (on_failure_callback).
- deadline_missed: la ejecución no ha terminado a tiempo (callback de la Deadline Alert).

Un fallo al publicar se registra pero nunca cambia el estado de la ejecución.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

SUBJECT_PREFIX = "[birds-pipeline]"
SUBJECT_MAX_LEN = 100
ERROR_MAX_LEN = 1000
HINT = "Abrir la UI con Session Manager (ver docs/airflow-operations.md)"


def _date_part(logical_date: Any) -> str:
    if logical_date is None:
        return "sin-fecha"
    if hasattr(logical_date, "strftime"):
        return logical_date.strftime("%Y-%m-%d")
    return str(logical_date)[:10]


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _subject(kind: str, name: str, date: str) -> str:
    fixed = f"{SUBJECT_PREFIX} {kind}  ({date})"
    room = SUBJECT_MAX_LEN - len(fixed)
    if len(name) > room:
        name = name[: max(room - 1, 0)] + "…"
    return f"{SUBJECT_PREFIX} {kind} {name} ({date})"


def build_failure_message(context: dict[str, Any]) -> tuple[str, str]:
    """Devuelve (asunto, cuerpo JSON) para una tarea fallida."""
    ti = context["ti"]
    dag_run = context.get("dag_run")
    logical_date = context.get("logical_date") or getattr(dag_run, "logical_date", None)
    error = str(context.get("exception") or "Error desconocido")[:ERROR_MAX_LEN]

    body = {
        "type": "task_failure",
        "dag_id": ti.dag_id,
        "run_id": ti.run_id,
        "logical_date": _iso(logical_date),
        "task_id": ti.task_id,
        "try_number": ti.try_number,
        "error": error,
        "log_url": getattr(ti, "log_url", None),
        "hint": HINT,
    }
    subject = _subject("FALLO", ti.task_id, _date_part(logical_date))
    return subject, json.dumps(body, ensure_ascii=False)


def build_deadline_message(dag_id: str, run_id: str | None, logical_date: Any) -> tuple[str, str]:
    """Devuelve (asunto, cuerpo JSON) para una ejecución que no terminó a tiempo."""
    body = {
        "type": "deadline_missed",
        "dag_id": dag_id,
        "run_id": run_id,
        "logical_date": _iso(logical_date),
        "log_url": f"http://localhost:8080/dags/{dag_id}",
        "hint": HINT,
    }
    subject = _subject("RETRASO", dag_id, _date_part(logical_date))
    return subject, json.dumps(body, ensure_ascii=False)


def _publish(subject: str, message: str) -> None:
    try:
        from airflow.providers.amazon.aws.hooks.sns import SnsHook

        SnsHook(aws_conn_id="aws_default").publish_to_target(
            target_arn=os.environ["BIRDS_ALERTS_TOPIC_ARN"],
            message=message,
            subject=subject,
        )
    except Exception:  # noqa: BLE001 — una alerta fallida no debe romper la ejecución
        log.exception("No se pudo publicar la alerta en SNS: %s", subject)


def notify_failure(context: dict[str, Any]) -> None:
    """on_failure_callback: solo se invoca cuando la tarea falla definitivamente."""
    subject, message = build_failure_message(context)
    _publish(subject, message)


def notify_deadline(
    dag_id: str = "nantes_birds_pipeline",
    run_id: str | None = None,
    logical_date: Any = None,
    context: dict[str, Any] | None = None,
    **_: Any,
) -> None:
    """Callback de la Deadline Alert (SyncCallback)."""
    if context:
        dag_run = context.get("dag_run")
        run_id = run_id or getattr(dag_run, "run_id", None)
        logical_date = logical_date or getattr(dag_run, "logical_date", None)
    subject, message = build_deadline_message(dag_id, run_id, logical_date)
    _publish(subject, message)
