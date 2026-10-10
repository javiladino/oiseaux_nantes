# Validation Results — Nantes Birds Pipeline

**Date**: Pending end-to-end execution against live AWS environment  
**Reference**: `specs/001-nantes-birds-pipeline/quickstart.md`

---

## Status Summary

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

## How to Run Validation

See `specs/001-nantes-birds-pipeline/quickstart.md` for step-by-step commands for each scenario.

Prerequisites:
- AWS CLI configured for `eu-west-3`
- Lambda `birds-inaturalist-ingestion` deployed
- S3 bucket with `BIRDS_S3_BUCKET` env var set
- Athena workgroup + Glue databases (`birds_raw`, `birds_dbt`) created
- dbt project installed: `pip install dbt-athena-community && cd dbt_birds && dbt deps`

Update this file with pass/fail results as each scenario is validated.
