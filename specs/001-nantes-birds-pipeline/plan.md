# Implementation Plan: Nantes Birds Biodiversity Pipeline

**Branch**: `001-nantes-birds-pipeline` | **Date**: 2026-10-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-nantes-birds-pipeline/spec.md`

## Summary

End-to-end ELT pipeline that ingests bird observations from iNaturalist's public API for the
Greater Nantes area, persists raw JSON to S3, and transforms it through a three-layer dbt
medallion architecture (staging → intermediate → marts) on AWS Athena into a star-schema
dimensional model consumed by Power BI. Ingestion is incremental, watermarked via SSM Parameter
Store, and orchestrated daily by EventBridge.

## Technical Context

**Language/Version**: Python 3.11+ (Lambda ingestion), SQL (dbt models)

**Primary Dependencies**:
- `requests` — iNaturalist API HTTP client in Lambda
- `boto3` — S3 write and SSM watermark read/write
- `dbt-core` + `dbt-athena-community` — medallion transformation layer
- `pytest` + `moto` — Lambda unit tests with mocked AWS

**Storage**:
- AWS S3 — raw zone (`raw/inaturalist/observations/year=YYYY/month=MM/`) and processed zone
  (Parquet, managed by dbt-athena)
- AWS Glue Data Catalog — schema registry for all Athena tables/views
- AWS Athena — serverless SQL query engine backing all dbt transformations
- AWS SSM Parameter Store — single `String` parameter persisting the ingestion watermark

**Testing**:
- Lambda: `pytest` with `moto` for S3/SSM mocking; integration test against real iNaturalist
  API (read-only, no side effects)
- dbt: built-in schema tests (`unique`, `not_null`, `accepted_values`, `relationships`);
  custom singular tests for bounding-box containment

**Target Platform**: AWS (Lambda + EventBridge for scheduling, S3 + Glue + Athena for the lake,
SSM for config, CloudWatch + SNS for alerting); Power BI Desktop / Service for consumption

**Project Type**: ELT data pipeline + analytics engineering project

**Performance Goals**:
- Ingestion respects iNaturalist rate limit (~1 req/s)
- Lambda cold + warm execution completes within 3-minute hard cap for typical daily volume
- Athena queries use partition pruning; per-query scan cost near zero

**Constraints**:
- Lambda timeout ≤ 3 minutes (constitution IV)
- Raw files stored as JSON (no transformation at ingest); processed files as Parquet + Snappy
- IAM role for Lambda: `s3:PutObject` on target prefix + `ssm:GetParameter`/`ssm:PutParameter`
  on the single watermark ARN + `logs:CreateLogGroup`/`logs:PutLogEvents`; no wildcard ARNs
- Watermark updated atomically only after successful S3 write; never updated on partial failure

**Scale/Scope**:
- Expected daily volume: hundreds of observations for the Nantes bounding box
- Star schema: 1 fact table + 3 dimension tables; `dim_date` covering full observed date range
- Power BI Import mode, daily scheduled refresh aligned with ingestion cadence

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Gate | Status | Notes |
|-----------|------|--------|-------|
| I. ELT Separation | Lambda does EL only; dbt does T; Power BI reads marts only | **PASS** | No transformation logic in Lambda |
| II. Ethical API | Incremental, ~1 req/s, identifiable `User-Agent` header | **PASS** | Full re-ingest gated behind manual trigger per spec |
| III. Zero-Failure DQ | dbt tests: PK uniqueness, geo bounds, `quality_grade` values | **PASS** | FR-008/010/015; SC-004 blocks promotion on any test failure |
| IV. Least-Privilege | IAM scoped to single S3 prefix + SSM ARN; Lambda ≤3min; Parquet+Snappy | **PASS** | FR-002 explicitly scopes SSM IAM |
| V. Idempotency & Docs | Dedup keyed on `observation_id`; every model has `.yml` docs + tests | **PASS** | FR-014/015 |

**No violations. Proceeding to Phase 0.**

## Project Structure

### Documentation (this feature)

```text
specs/001-nantes-birds-pipeline/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── inaturalist-api.md
│   └── dbt-models.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
ingestion/                          # Lambda package (Python 3.11+)
├── handler.py                      # Lambda entry point; orchestrates fetch → write → watermark
├── inaturalist_client.py           # HTTP client: paginated GET /v1/observations, rate limiting
├── s3_writer.py                    # Writes raw JSON batches to S3 with correct partition key
├── ssm_watermark.py                # Atomic SSM get/put for incremental watermark
└── requirements.txt                # requests, boto3

tests/
├── unit/
│   ├── test_inaturalist_client.py
│   ├── test_s3_writer.py
│   └── test_ssm_watermark.py
└── integration/
    └── test_ingestion_e2e.py       # Live iNaturalist API + localstack or real AWS

dbt_birds/                          # dbt project root
├── dbt_project.yml
├── profiles.yml                    # Athena connection (s3_staging_dir, region, catalog)
├── models/
│   ├── sources/
│   │   └── sources.yml             # raw_inaturalist external table definition
│   ├── staging/
│   │   ├── stg_inaturalist__observations.sql
│   │   └── stg_inaturalist__observations.yml
│   ├── intermediate/
│   │   ├── int_observations__geospatial_enriched.sql
│   │   └── int_observations__geospatial_enriched.yml
│   └── marts/
│       ├── fct_observations.sql
│       ├── fct_observations.yml
│       ├── dim_species.sql
│       ├── dim_species.yml
│       ├── dim_users.sql
│       ├── dim_users.yml
│       ├── dim_date.sql
│       └── dim_date.yml
└── tests/
    └── assert_observations_within_nantes_bbox.sql

.github/
└── workflows/
    └── dbt_ci.yml                  # dbt test on PR; fail workflow on any test failure
```

**Structure Decision**: Single-repository layout with `ingestion/` (Lambda Python) and
`dbt_birds/` (dbt project) as sibling top-level directories. Infrastructure (Terraform) is
explicitly out of scope per spec assumptions. GitHub Actions CI lives in `.github/workflows/`.

## Complexity Tracking

> No constitution violations detected. This section is intentionally empty.
