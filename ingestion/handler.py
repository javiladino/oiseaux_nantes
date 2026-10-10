import os
import boto3
from datetime import datetime, timezone

from inaturalist_client import fetch_observations
from s3_writer import write_batch
from ssm_watermark import get_watermark, put_watermark, PARAM_NAME

BUCKET = os.environ["BIRDS_S3_BUCKET"]


def lambda_handler(event, context):
    ssm = boto3.client("ssm", region_name="eu-west-3")
    s3 = boto3.client("s3", region_name="eu-west-3")

    watermark = get_watermark(ssm, PARAM_NAME)
    observations = fetch_observations(watermark)

    if not observations:
        return {"statusCode": 200, "body": "Ingested 0 observations"}

    run_ts = datetime.now(timezone.utc)
    # Write all observations as a single batch; the write must fully succeed before
    # the watermark is updated (constitution IV + FR-002).
    write_batch(s3, BUCKET, observations, run_ts)

    put_watermark(ssm, PARAM_NAME, run_ts.strftime("%Y-%m-%dT%H:%M:%S"))

    return {"statusCode": 200, "body": f"Ingested {len(observations)} observations"}
