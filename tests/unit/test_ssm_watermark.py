import boto3
import pytest
from moto import mock_aws

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../ingestion"))

from ssm_watermark import get_watermark, put_watermark

PARAM = "/birds-pipeline/last_successful_run_date"


@pytest.fixture
def ssm(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-3")
    with mock_aws():
        yield boto3.client("ssm", region_name="eu-west-3")


def test_get_watermark_returns_none_when_not_found(ssm):
    result = get_watermark(ssm, PARAM)
    assert result is None


def test_get_watermark_returns_value_when_exists(ssm):
    ssm.put_parameter(Name=PARAM, Value="2024-05-01T10:00:00", Type="String")
    result = get_watermark(ssm, PARAM)
    assert result == "2024-05-01T10:00:00"


def test_put_watermark_creates_on_first_call(ssm):
    put_watermark(ssm, PARAM, "2024-05-01T10:00:00")
    resp = ssm.get_parameter(Name=PARAM)
    assert resp["Parameter"]["Value"] == "2024-05-01T10:00:00"


def test_put_watermark_overwrites_on_subsequent_calls(ssm):
    put_watermark(ssm, PARAM, "2024-05-01T10:00:00")
    put_watermark(ssm, PARAM, "2024-05-02T10:00:00")
    resp = ssm.get_parameter(Name=PARAM)
    assert resp["Parameter"]["Value"] == "2024-05-02T10:00:00"
