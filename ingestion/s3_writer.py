import json
from datetime import datetime


def write_batch(s3_client, bucket: str, observations: list[dict], run_ts: datetime) -> str:
    """Write a list of observations as NDJSON to the correct S3 partition, return the S3 key."""
    year = run_ts.strftime("%Y")
    month = run_ts.strftime("%m")
    timestamp = run_ts.strftime("%Y%m%dT%H%M%S")
    key = f"raw/inaturalist/observations/year={year}/month={month}/{timestamp}.json"

    ndjson = "\n".join(json.dumps(obs, ensure_ascii=False) for obs in observations)
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=ndjson.encode("utf-8"),
        ContentType="application/x-ndjson",
    )
    return key
