"""Mensajes de alerta según specs/002-airflow-orchestration/contracts/alert-message.md."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import alerts
import pytest

LOGICAL_DATE = datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)


def _context(task_id="ingest_inaturalist", error="boom"):
    ti = SimpleNamespace(
        dag_id="nantes_birds_pipeline",
        run_id="scheduled__2026-10-12T05:00:00+00:00",
        task_id=task_id,
        try_number=3,
        log_url="http://localhost:8080/log",
    )
    return {"ti": ti, "logical_date": LOGICAL_DATE, "exception": RuntimeError(error)}


def test_failure_subject_and_body():
    subject, message = alerts.build_failure_message(_context())
    assert subject == "[birds-pipeline] FALLO ingest_inaturalist (2026-10-12)"

    body = json.loads(message)
    assert body["type"] == "task_failure"
    assert body["dag_id"] == "nantes_birds_pipeline"
    assert body["run_id"] == "scheduled__2026-10-12T05:00:00+00:00"
    assert body["logical_date"] == "2026-10-12T05:00:00+00:00"
    assert body["task_id"] == "ingest_inaturalist"
    assert body["try_number"] == 3
    assert body["error"] == "boom"
    assert body["log_url"]
    assert body["hint"]


def test_subject_max_100_chars():
    long_task = "dbt_medallion." + "x" * 200 + ".test"
    subject, _ = alerts.build_failure_message(_context(task_id=long_task))
    assert len(subject) <= 100
    assert subject.endswith("(2026-10-12)")


def test_error_truncated_to_1000_chars():
    _, message = alerts.build_failure_message(_context(error="e" * 5000))
    assert len(json.loads(message)["error"]) == 1000


def test_deadline_message():
    subject, message = alerts.build_deadline_message(
        "nantes_birds_pipeline", "scheduled__2026-10-12T05:00:00+00:00", LOGICAL_DATE
    )
    assert subject == "[birds-pipeline] RETRASO nantes_birds_pipeline (2026-10-12)"
    body = json.loads(message)
    assert body["type"] == "deadline_missed"
    assert "task_id" not in body
    assert "error" not in body


def test_notify_failure_publishes_to_topic():
    with mock.patch("airflow.providers.amazon.aws.hooks.sns.SnsHook.publish_to_target") as publish:
        alerts.notify_failure(_context())
    publish.assert_called_once()
    kwargs = publish.call_args.kwargs
    assert kwargs["target_arn"] == "arn:aws:sns:eu-west-3:000000000000:birds-pipeline-alerts"
    assert kwargs["subject"].startswith("[birds-pipeline] FALLO")


def test_notify_failure_never_raises():
    with mock.patch(
        "airflow.providers.amazon.aws.hooks.sns.SnsHook.publish_to_target",
        side_effect=RuntimeError("SNS caído"),
    ):
        alerts.notify_failure(_context())  # no debe propagar la excepción


@pytest.mark.parametrize("ctx_date", [LOGICAL_DATE, None])
def test_notify_deadline_accepts_context(ctx_date):
    dag_run = SimpleNamespace(run_id="manual__x", logical_date=ctx_date)
    with mock.patch("airflow.providers.amazon.aws.hooks.sns.SnsHook.publish_to_target") as publish:
        alerts.notify_deadline(context={"dag_run": dag_run})
    assert publish.call_args.kwargs["subject"].startswith("[birds-pipeline] RETRASO")
