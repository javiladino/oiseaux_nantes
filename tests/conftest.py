import os
import boto3
import pytest
from moto import mock_aws


SSM_PARAM_NAME = "/birds-pipeline/last_successful_run_date"


@pytest.fixture
def aws_credentials():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "eu-west-3"


@pytest.fixture
def s3_bucket(aws_credentials):
    with mock_aws():
        client = boto3.client("s3", region_name="eu-west-3")
        client.create_bucket(
            Bucket="test-birds-bucket",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-3"},
        )
        yield client


@pytest.fixture
def ssm_client(aws_credentials):
    with mock_aws():
        yield boto3.client("ssm", region_name="eu-west-3")


@pytest.fixture
def ssm_param_name():
    return SSM_PARAM_NAME
