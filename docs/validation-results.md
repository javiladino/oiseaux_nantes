# Validation Results — Nantes Birds Pipeline

**Reference**: `specs/001-nantes-birds-pipeline/quickstart.md`

---

## Unit Test Results (No Live AWS Required)

Executed via `PYTHONPATH=ingestion pytest tests/unit/ -v`:

| Module | Tests | Result |
|--------|-------|--------|
| `test_inaturalist_client.py` | 6 | ✅ PASS |
| `test_s3_writer.py` | 4 | ✅ PASS |
| `test_ssm_watermark.py` | 4 | ✅ PASS |
| **Total** | **14** | **✅ 14/14 PASS** |

---

## End-to-End Scenario Status (Requires Live AWS)

| Scenario | Description | Status | Notes |
|----------|-------------|--------|-------|
| 1 | First-run ingestion | PENDING | Requires live Lambda + S3 + SSM |
| 2 | Incremental run — no duplicates | PENDING | Requires Scenario 1 baseline |
| 3 | dbt staging model validation | PENDING | Requires raw data in S3 + Athena |
| 4 | Intermediate bbox validation | PENDING | Requires Scenario 3 baseline |
| 5 | Full mart layer star schema integrity | PENDING | Requires Scenario 4 baseline |
| 6 | Power BI end-to-end refresh | PENDING | Requires Scenario 5 + Power BI Desktop |
| 7 | Idempotency under failure | PENDING | Requires Scenarios 1–2 complete |

---

## How to Run End-to-End Validation

See `specs/001-nantes-birds-pipeline/quickstart.md` for step-by-step commands for each scenario.

Prerequisites:
- AWS CLI configured for `eu-west-3`
- Lambda `birds-inaturalist-ingestion` deployed with env var `BIRDS_S3_BUCKET`
- S3 bucket with `raw/inaturalist/` prefix
- SSM parameter `/birds-pipeline/last_successful_run_date` (absent = first run)
- Athena workgroup + Glue databases (`birds_raw`, `birds_dbt`) created
- dbt project installed: `pip install dbt-athena-community && cd dbt_birds && dbt deps`
- For Scenario 6: Power BI Desktop with Amazon Athena ODBC driver

Update the table above with pass/fail results as each scenario is validated against the live environment.
