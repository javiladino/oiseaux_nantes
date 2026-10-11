"""Fixtures de los tests del DAG nantes_birds_pipeline.

Requiere Airflow 3.3.2, Cosmos y dbt instalados, y el manifest de dbt generado antes con:
    cd dbt_birds && dbt deps && \
    BIRDS_S3_BUCKET=ci-placeholder dbt parse --profiles-dir ../orchestration/config --target ci
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DAGS_DIR = REPO_ROOT / "orchestration" / "dags"
PLUGINS_DIR = REPO_ROOT / "orchestration" / "plugins"
MANIFEST = REPO_ROOT / "dbt_birds" / "target" / "manifest.json"

# Variables de entorno antes de importar Airflow.
os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="airflow-test-"))
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "False")
os.environ.setdefault("AIRFLOW__CORE__UNIT_TEST_MODE", "True")
os.environ.setdefault("BIRDS_S3_BUCKET", "test-bucket")
os.environ.setdefault("BIRDS_ALERTS_TOPIC_ARN", "arn:aws:sns:eu-west-3:000000000000:birds-pipeline-alerts")
os.environ.setdefault("DBT_PROJECT_DIR", str(REPO_ROOT / "dbt_birds"))
os.environ.setdefault("DBT_PROFILES_DIR", str(REPO_ROOT / "orchestration" / "config"))
os.environ.setdefault("DBT_EXECUTABLE_PATH", shutil.which("dbt") or "dbt")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-3")

# Airflow añade plugins_folder a sys.path en producción; en los tests lo hacemos a mano.
if str(PLUGINS_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGINS_DIR))

DAG_ID = "nantes_birds_pipeline"


def _dagbag_class():
    try:  # Airflow ≥ 3.1
        from airflow.dag_processing.dagbag import DagBag
    except ImportError:  # pragma: no cover
        from airflow.models.dagbag import DagBag
    return DagBag


@pytest.fixture(scope="session")
def dagbag():
    if not MANIFEST.exists():
        pytest.fail(f"Falta {MANIFEST}: ejecutar `dbt parse --target ci` antes de los tests")
    # Los DAGs de ejemplo ya están excluidos por AIRFLOW__CORE__LOAD_EXAMPLES=False
    # (en Airflow 3.3 DagBag no acepta include_examples).
    return _dagbag_class()(dag_folder=str(DAGS_DIR))


@pytest.fixture(scope="session")
def dag(dagbag):
    # dagbag.get_dag() consulta la base de metadatos en Airflow 3; aquí basta con lo parseado.
    loaded = dagbag.dags.get(DAG_ID)
    assert loaded is not None, f"El DAG {DAG_ID} no se cargó: {dagbag.import_errors}"
    return loaded
