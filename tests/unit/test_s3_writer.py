import json
import re
import boto3
import pytest
from datetime import datetime, timezone
from moto import mock_aws

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../ingestion"))

from s3_writer import write_batch

BUCKET = "test-birds-bucket"


@pytest.fixture
def s3(aws_credentials):
    with mock_aws():
        client = boto3.client("s3", region_name="eu-west-3")
        client.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "eu-west-3"},
        )
        yield client


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-3")


def test_output_key_matches_partition_pattern(s3):
    run_ts = datetime(2024, 5, 15, 10, 30, 0, tzinfo=timezone.utc)
    key = write_batch(s3, BUCKET, [{"id": 1}], run_ts)
    assert re.match(r"raw/inaturalist/observations/year=2024/month=05/\d{8}T\d{6}\.json", key)


def test_file_content_is_valid_ndjson(s3):
    run_ts = datetime(2024, 5, 15, 10, 30, 0, tzinfo=timezone.utc)
    obs = [{"id": 1, "name": "Pigeon"}, {"id": 2, "name": "Goéland"}]
    key = write_batch(s3, BUCKET, obs, run_ts)
    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read().decode("utf-8")
    lines = body.strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert "id" in parsed


def test_multiple_batches_written_to_separate_files(s3):
    run_ts1 = datetime(2024, 5, 15, 10, 0, 0, tzinfo=timezone.utc)
    run_ts2 = datetime(2024, 5, 15, 10, 1, 0, tzinfo=timezone.utc)
    k1 = write_batch(s3, BUCKET, [{"id": 1}], run_ts1)
    k2 = write_batch(s3, BUCKET, [{"id": 2}], run_ts2)
    assert k1 != k2


def test_utf8_encoding_preserved(s3):
    run_ts = datetime(2024, 5, 15, 10, 0, 0, tzinfo=timezone.utc)
    obs = [{"id": 1, "name": "Mésange bleue"}]
    key = write_batch(s3, BUCKET, obs, run_ts)
    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read().decode("utf-8")
    assert "Mésange bleue" in body
