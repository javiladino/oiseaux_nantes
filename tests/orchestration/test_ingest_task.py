"""Comportamiento de la tarea de ingesta ante respuestas de la Lambda (FR-003)."""

import io
import json
from unittest import mock

import pytest
from airflow.providers.amazon.aws.hooks.lambda_function import LambdaHook


def _response(payload: dict, function_error: str | None = None) -> dict:
    resp = {
        "StatusCode": 200,
        "ResponseMetadata": {"RequestId": "test", "HTTPStatusCode": 200},
        "Payload": io.BytesIO(json.dumps(payload).encode()),
    }
    if function_error:
        resp["FunctionError"] = function_error
    return resp


@pytest.fixture
def ingest(dag):
    return dag.get_task("ingest_inaturalist")


def test_success_returns_payload(ingest):
    ok = _response({"statusCode": 200, "body": "Ingested 3 observations"})
    with mock.patch.object(LambdaHook, "invoke_lambda", return_value=ok):
        result = ingest.execute(context={})
    assert "Ingested 3 observations" in str(result)


def test_function_error_fails_task(ingest):
    failed = _response({"errorMessage": "boom", "errorType": "RuntimeError"}, function_error="Unhandled")
    with mock.patch.object(LambdaHook, "invoke_lambda", return_value=failed):
        with pytest.raises(ValueError, match="Lambda function execution resulted in error"):
            ingest.execute(context={})
