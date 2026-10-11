"""Pipeline diario de aves de Nantes: ingesta (Lambda) → transformación medallón (dbt).

Contrato: specs/002-airflow-orchestration/contracts/dag-interface.md

- 05:00 UTC: invoca la Lambda de ingesta existente (sin cambios; el watermark sigue en SSM).
- Si la ingesta termina bien, ejecuta cada modelo dbt como una pareja run → test (Cosmos,
  TestBehavior.AFTER_EACH); los modelos dependientes solo corren si los tests del padre pasan.
- Reintentos (2 × 5 min) y alerta SNS cuando una tarea falla definitivamente.
- Deadline Alert si la ejecución no ha terminado a las 07:00 UTC (antes del refresco de Power BI).
- Parámetro full_refresh: reconstruye los modelos dbt incrementales; no afecta a la ingesta.
- Power BI queda fuera del DAG (refresco programado a las 08:00 UTC).
"""

import os
from datetime import datetime, timedelta, timezone

from airflow.providers.amazon.aws.operators.lambda_function import LambdaInvokeFunctionOperator
from airflow.sdk import DAG, DeadlineAlert, DeadlineReference, Param, SyncCallback
from alerts import notify_deadline, notify_failure
from cosmos import (
    DbtTaskGroup,
    ExecutionConfig,
    LoadMode,
    ProfileConfig,
    ProjectConfig,
    RenderConfig,
    TestBehavior,
)

DBT_PROJECT_DIR = os.environ.get("DBT_PROJECT_DIR", "/opt/oiseaux_nantes/dbt_birds")
DBT_PROFILES_DIR = os.environ.get("DBT_PROFILES_DIR", "/opt/oiseaux_nantes/orchestration/config")
DBT_EXECUTABLE_PATH = os.environ.get("DBT_EXECUTABLE_PATH", "/opt/dbt-venv/bin/dbt")

INGESTION_FUNCTION = "birds-inaturalist-ingestion"

with DAG(
    dag_id="nantes_birds_pipeline",
    description="Ingesta iNaturalist (Lambda) → dbt staging/intermediate/marts en Athena",
    schedule="0 5 * * *",
    start_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "on_failure_callback": notify_failure,
    },
    params={
        "full_refresh": Param(
            False,
            type="boolean",
            description=(
                "Reconstruye desde cero los modelos dbt incrementales a partir de los datos raw "
                "de S3. No afecta a la ingesta ni al watermark."
            ),
        ),
    },
    deadline=DeadlineAlert(
        reference=DeadlineReference.DAGRUN_LOGICAL_DATE,
        interval=timedelta(hours=2),  # 05:00 + 2 h = 07:00 UTC
        callback=SyncCallback(
            notify_deadline,
            kwargs={
                "dag_id": "{{ dag_run.dag_id }}",
                "run_id": "{{ dag_run.run_id }}",
                "logical_date": "{{ dag_run.logical_date }}",
            },
        ),
    ),
    tags=["nantes-birds", "elt"],
) as dag:
    ingest = LambdaInvokeFunctionOperator(
        task_id="ingest_inaturalist",
        function_name=INGESTION_FUNCTION,
        invocation_type="RequestResponse",
        payload="{}",
        log_type="Tail",
        aws_conn_id="aws_default",
        # La Lambda tarda hasta 3 min; los reintentos los gestiona Airflow, no botocore.
        botocore_config={"read_timeout": 200, "connect_timeout": 10, "retries": {"max_attempts": 0}},
    )

    transform = DbtTaskGroup(
        group_id="dbt_medallion",
        project_config=ProjectConfig(
            dbt_project_path=DBT_PROJECT_DIR,
            manifest_path=f"{DBT_PROJECT_DIR}/target/manifest.json",
            # deploy.sh ya ejecuta `dbt deps`; no repetirlo en cada tarea.
            install_dbt_deps=False,
        ),
        profile_config=ProfileConfig(
            profile_name="birds_pipeline",
            target_name="prod",
            profiles_yml_filepath=f"{DBT_PROFILES_DIR}/profiles.yml",
        ),
        execution_config=ExecutionConfig(dbt_executable_path=DBT_EXECUTABLE_PATH),
        render_config=RenderConfig(
            load_method=LoadMode.DBT_MANIFEST,
            test_behavior=TestBehavior.AFTER_EACH,
        ),
        # Solo los operadores run usan full_refresh; Cosmos lo descarta en los de test.
        operator_args={"full_refresh": "{{ params.full_refresh }}"},
    )

    ingest >> transform
