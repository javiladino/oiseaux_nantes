"""Integridad del DAG según specs/002-airflow-orchestration/contracts/dag-interface.md (puntos ✔)."""

from datetime import timedelta

import pytest

INGEST = "ingest_inaturalist"
GROUP = "dbt_medallion"
MODELS = [
    "stg_inaturalist__observations",
    "int_observations__geospatial_enriched",
    "dim_species",
    "dim_users",
    "dim_date",
    "fct_observations",
]


def _run(model):
    return f"{GROUP}.{model}.run"


def _test(model):
    return f"{GROUP}.{model}.test"


# --- US1: identificación, programación y estructura -------------------------------------


def test_no_import_errors(dagbag):
    assert dagbag.import_errors == {}


def test_identity_and_schedule(dag):
    assert dag.dag_id == "nantes_birds_pipeline"
    assert dag.schedule == "0 5 * * *"
    assert str(dag.timezone) in {"UTC", "Timezone('UTC')"}
    assert dag.catchup is False
    assert dag.max_active_runs == 1


def test_ingest_task_is_root(dag):
    task = dag.get_task(INGEST)
    assert task.upstream_task_ids == set()
    assert task.function_name == "birds-inaturalist-ingestion"
    assert task.invocation_type == "RequestResponse"


@pytest.mark.parametrize("model", MODELS)
def test_each_model_has_run_and_test(dag, model):
    assert dag.has_task(_run(model))
    assert dag.has_task(_test(model))
    assert _run(model) in dag.get_task(_test(model)).upstream_task_ids


def test_every_dbt_task_depends_on_ingestion(dag):
    ingest_downstream = dag.get_task(INGEST).get_flat_relative_ids(upstream=False)
    dbt_tasks = {t for t in dag.task_ids if t.startswith(f"{GROUP}.")}
    assert dbt_tasks, "El grupo dbt_medallion está vacío"
    assert dbt_tasks <= ingest_downstream


def test_model_order_follows_tests(dag):
    int_run = dag.get_task(_run("int_observations__geospatial_enriched"))
    assert _test("stg_inaturalist__observations") in int_run.upstream_task_ids

    for dim in ("dim_species", "dim_users", "dim_date"):
        dim_run = dag.get_task(_run(dim))
        assert _test("int_observations__geospatial_enriched") in dim_run.upstream_task_ids

    fct_upstream = dag.get_task(_run("fct_observations")).get_flat_relative_ids(upstream=True)
    for dim in ("dim_species", "dim_users", "dim_date"):
        assert _test(dim) in fct_upstream


def test_no_tasks_outside_contract(dag):
    # FR-016: Power BI queda fuera del DAG.
    extra = {t for t in dag.task_ids if t != INGEST and not t.startswith(f"{GROUP}.")}
    assert extra == set()


# --- US2: reintentos y alertas -----------------------------------------------------------


def test_default_args_retries_and_callback(dag):
    from alerts import notify_failure

    assert dag.default_args["retries"] == 2
    assert dag.default_args["retry_delay"] == timedelta(minutes=5)
    assert dag.default_args["on_failure_callback"] is notify_failure


def test_all_tasks_inherit_retries(dag):
    for task in dag.tasks:
        assert task.retries == 2, task.task_id


# --- US3: reconstrucción completa ---------------------------------------------------------


def test_full_refresh_param(dag):
    param = dag.params.get_param("full_refresh")
    assert param.value is False
    assert param.schema.get("type") == "boolean"


def test_full_refresh_only_on_dbt_runs(dag):
    ingest = dag.get_task(INGEST)
    for field in ingest.template_fields:
        assert "full_refresh" not in str(getattr(ingest, field, ""))

    for model in MODELS:
        task = dag.get_task(_run(model))
        assert task.full_refresh == "{{ params.full_refresh }}"
