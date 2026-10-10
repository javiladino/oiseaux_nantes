<!--
## Sync Impact Report
Generated: 2026-10-10
---
Version change: [unversioned / blank scaffold] → 1.0.0 (MAJOR — initial ratification)

Added sections:
  - Project Vision & Purpose (preamble, before Core Principles)
  - Core Principles (5 principles — all new):
      I.   ELT Separation of Concerns
      II.  Ethical API Ingestion & Rate Limiting
      III. Zero-Failure Data Quality (NON-NEGOTIABLE)
      IV.  Least-Privilege Security & Cost Governance
      V.   Idempotency & Documentation
  - Technology Stack & Roles (Section 2 — new)
  - dbt Medallion Modeling Standards (Section 3 — new)
  - Governance (new)

Modified principles: N/A (initial ratification)
Removed sections: N/A

Deferred TODOs:
  - RATIFICATION_DATE set to 2026-10-10 (today). Update if the project was started earlier.

This comment is scratch material for human review. Remove before committing.
-->

# Nantes Biodiversity Analytics Pipeline Constitution

## Project Vision & Purpose

Build a scalable, robust, and cost-effective end-to-end Modern Data Stack (MDS) pipeline to
ingest, clean, model, and visualize citizen science wildlife observations (specifically Aves in
Nantes, France) from the open-source platform iNaturalist.

This pipeline serves as an analytical reference project demonstrating senior Data Engineering
best practices: Serverless EL (Extract & Load), Analytics Engineering via dbt, and Business
Intelligence via Power BI.

## Core Principles

### I. ELT Separation of Concerns

**Ingestion (EL):** AWS Lambda is solely responsible for data extraction and persistence to
object storage (AWS S3). Lambda MUST NOT perform heavy analytical transformations.

**Storage (Data Lake):** S3 is the single source of truth. Raw data MUST be partitioned
temporally (`raw/dataset/year=YYYY/month=MM/`).

**Transformation (T):** All analytical transformations MUST be executed by dbt using in-place
SQL on AWS Athena. No row-level processing in Lambda.

**Serving & BI:** Power BI MUST consume only modeled and curated data marts (`marts/`). Direct
access to raw or staging layers is prohibited.

*Rationale: Keeping ingestion, storage, transformation, and serving concerns cleanly separated
enables independent scaling, testability, and auditability of each layer.*

### II. Ethical API Ingestion & Rate Limiting

Ingestion MUST strictly respect iNaturalist API rate limits (~1 request per second).

All API calls MUST include an identifiable `User-Agent` header that identifies this project.

Ingestion MUST run on an incremental basis, capturing only newly created or newly observed
records since the last successful run. Full re-ingestion MUST be explicitly justified and
gated behind a manual trigger.

*Rationale: Responsible use of the iNaturalist public API protects the upstream service and
the project's continued access to the data.*

### III. Zero-Failure Data Quality (NON-NEGOTIABLE)

Raw JSON MUST be stored exactly as received (schema-drift tolerant at the raw layer).

Before promotion to production marts, dbt tests MUST enforce:
- `observation_id` is unique and non-null (primary key integrity).
- Latitude and longitude fall within the bounding box of Greater Nantes.
- `quality_grade` values match iNaturalist taxonomy: `research`, `needs_id`, or `casual`.

A dbt model MUST NOT be merged to `main` if any schema test fails.

*Rationale: Downstream Power BI dashboards and analytical queries depend on trustworthy data.
Silent data corruption is worse than a visible pipeline failure.*

### IV. Least-Privilege Security & Cost Governance

**IAM:** Lambda execution roles MUST carry only `s3:PutObject` on the target S3 prefix and
CloudWatch Logs write permissions. No wildcard resource ARNs are permitted.

**Lambda:** Function timeout MUST be capped at 3 minutes.

**Athena:** All processed data MUST be stored as Parquet with Snappy compression. Queries MUST
use partition pruning (`year`, `month` predicates) to keep per-query scan costs near zero.

*Rationale: The project targets near-zero operating cost. Over-provisioned IAM roles create
unnecessary security blast radius; unoptimized Athena scans are the primary cost driver.*

### V. Idempotency & Documentation

**Idempotency:** Any execution of the ingestion Lambda or any dbt run MUST produce the same
final state regardless of how many times it is re-run. Deduplication MUST be keyed on
`observation_id`.

**Documentation:** Every dbt model and every column MUST be documented in its companion `.yml`
file with at least one dbt test attached. A PR that adds or modifies a model without updating
its `.yml` MUST NOT be merged to `main`.

*Rationale: Idempotency makes the pipeline safe to retry after failures without manual
cleanup. Mandatory documentation ensures the project remains legible as a reference
implementation.*

## Technology Stack & Roles

| Layer | Technology | Primary Function |
| :--- | :--- | :--- |
| **Ingestion Engine** | AWS Lambda (Python 3.11+) | Serverless incremental API consumer |
| **Scheduler** | Amazon EventBridge | Cron orchestration for periodic ingestion |
| **Storage / Lake** | AWS S3 | Raw zone (JSON) and Processed zone (Parquet) |
| **Catalog & Schema** | AWS Glue Data Catalog | Metadata crawler and table definitions |
| **Compute Engine** | AWS Athena | Serverless distributed SQL query engine |
| **Transformation** | dbt-core / dbt-athena | Lineage, modeling, testing, documentation |
| **Visualization** | Power BI Desktop / Service | Dashboards, geospatial maps, taxonomic trends |
| **IaC & CI/CD** | Terraform & GitHub Actions | Reproducible infrastructure, automated dbt tests |

Any change to the technology stack MUST be recorded as a constitution amendment (MINOR bump
minimum) before implementation begins.

## dbt Medallion Modeling Standards

All dbt models MUST adhere to the following three-layer medallion architecture:

```
raw_inaturalist (S3 / Athena External Table)
       │
       ▼
stg_inaturalist__observations.sql
  (Staging: cast types, rename columns, flatten JSON, preliminary dedup)
       │
       ▼
int_observations__geospatial_enriched.sql
  (Intermediate: spatial validation, date logic, daylight period categorization)
       │
       ├───────────────────────────────────┐
       ▼                                   ▼
fct_observations.sql               dim_species.sql
  (Marts: star schema for Power BI analytical querying)
```

**Staging (`stg_`):** 1:1 mapping with the raw source. Type casting, uniform snake_case column
naming, and preliminary deduplication only. No business logic permitted here.

**Intermediate (`int_`):** Joins between staging models and business logic (e.g., categorizing
observation times into daylight periods, spatial enrichment). No direct raw source references.

**Marts (`fct_`, `dim_`):** Dimensional star schema optimized for fast Power BI querying.
Power BI MUST reference only this layer.

Skipping a layer (e.g., staging directly to mart) is prohibited without an explicit
constitution amendment.

## Governance

This constitution supersedes all other project practices and conventions. In case of conflict
between this document and any other guideline, this document takes precedence.

**Amendment Procedure:**
1. Open a PR modifying `.specify/memory/constitution.md`.
2. Increment the version following semantic versioning:
   - **MAJOR:** Backward-incompatible removal or redefinition of an existing principle.
   - **MINOR:** New principle, new section, or materially expanded guidance.
   - **PATCH:** Clarifications, wording fixes, non-semantic refinements.
3. The PR description MUST explain the rationale for the amendment.
4. At least one reviewer MUST approve before merging to `main`.

**Compliance:** All PRs MUST be reviewed for compliance with this constitution before merging.
Complexity added beyond what a feature requires MUST be explicitly justified against the
principles above.

**Version**: 1.0.0 | **Ratified**: 2026-10-10 | **Last Amended**: 2026-10-10
