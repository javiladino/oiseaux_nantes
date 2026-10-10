PARAM_NAME = "/birds-pipeline/last_successful_run_date"


def get_watermark(ssm_client, param_name: str) -> str | None:
    try:
        resp = ssm_client.get_parameter(Name=param_name)
        return resp["Parameter"]["Value"]
    except ssm_client.exceptions.ParameterNotFound:
        return None


def put_watermark(ssm_client, param_name: str, value: str) -> None:
    ssm_client.put_parameter(
        Name=param_name,
        Value=value,
        Type="String",
        Overwrite=True,
    )
