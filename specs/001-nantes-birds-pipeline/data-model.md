# Data Model: Nantes Birds Biodiversity Pipeline

**Feature**: `001-nantes-birds-pipeline` | **Date**: 2026-10-10

## Architecture Overview

```
S3 (raw JSON, partitioned year/month)
  └── Athena External Table: raw_inaturalist.observations
        │
        ▼
  stg_inaturalist__observations       [Staging — 1:1 raw; cast, flatten, dedup]
        │
        ▼
  int_observations__geospatial_enriched  [Intermediate — spatial filter, time period, flags]
        │
        ├──────────────────────────────────────────┐
        ▼                                          ▼
  fct_observations (FACT)                   dim_species (DIM)
  dim_users (DIM)                           dim_date (DIM)
```

Star schema in `marts/` layer consumed by Power BI. Power BI MUST NOT access staging or
intermediate layers directly.

---

## Raw Source

### `raw_inaturalist.observations` (External Athena Table)

| Column | Type | Notes |
|--------|------|-------|
| `raw_json` | STRING | Full JSON response object per observation, stored as-is |
| `year` | STRING | Hive partition key derived from `created_at` |
| `month` | STRING | Hive partition key derived from `created_at` |

- **Format**: One JSON object per line (NDJSON) per S3 file
- **S3 Path**: `s3://{bucket}/raw/inaturalist/observations/year={YYYY}/month={MM}/`
- **SerDe**: `org.openx.data.jsonserde.JsonSerDe`
- **Managed by**: Lambda ingestion; DDL registered via `dbt-external-tables`
- **Schema drift**: Tolerated at this layer; new fields are ignored by downstream models

---

## Staging Layer

### `stg_inaturalist__observations`

**Purpose**: 1:1 mapping of the raw source. Cast types, rename to snake_case, flatten nested
JSON structures, preliminary dedup on `observation_id`. No business logic.

**Materialization**: `view` (no storage cost; always reflects current raw data)

| Column | Type | Source | Transformation |
|--------|------|--------|----------------|
| `observation_id` | BIGINT | `id` | Cast to BIGINT; PK |
| `created_at_utc` | TIMESTAMP | `created_at` | Parse ISO 8601; normalize to UTC |
| `observed_on` | DATE | `observed_on` | Parse `YYYY-MM-DD` |
| `latitude` | DOUBLE | `location` | Split `"lat,lng"` string on `,`; index 0 |
| `longitude` | DOUBLE | `location` | Split `"lat,lng"` string on `,`; index 1 |
| `positional_accuracy_m` | INT | `positional_accuracy` | Direct cast; nullable |
| `quality_grade` | VARCHAR | `quality_grade` | Direct; validated in tests |
| `taxon_id` | BIGINT | `taxon.id` | Flatten nested object |
| `taxon_scientific_name` | VARCHAR | `taxon.name` | Flatten |
| `taxon_common_name` | VARCHAR | `taxon.preferred_common_name` | Flatten; nullable |
| `taxon_rank` | VARCHAR | `taxon.rank` | Flatten |
| `taxon_threatened` | BOOLEAN | `taxon.threatened` | Flatten |
| `user_id` | BIGINT | `user.id` | Flatten nested object |
| `user_login` | VARCHAR | `user.login` | Flatten |
| `user_display_name` | VARCHAR | `user.name` | Flatten; nullable |
| `_ingested_year` | STRING | partition `year` | Pass-through for downstream partitioning |
| `_ingested_month` | STRING | partition `month` | Pass-through for downstream partitioning |

**dbt tests**:
- `observation_id`: `unique`, `not_null`
- `quality_grade`: `accepted_values: [research, needs_id, casual]`
- `latitude`: `not_null`
- `longitude`: `not_null`
- `taxon_id`: `not_null`
- `user_id`: `not_null`

**Dedup logic**: `ROW_NUMBER() OVER (PARTITION BY observation_id ORDER BY created_at_utc DESC) = 1`

---

## Intermediate Layer

### `int_observations__geospatial_enriched`

**Purpose**: Business logic layer. Applies spatial validation (Greater Nantes bounding box),
time-of-day classification, and research-grade flag. No staging model references permitted
in marts.

**Materialization**: `view`

**Inputs**: `stg_inaturalist__observations`

**Bounding box filter** (FR-005):
```
swlat = 46.8600781, swlng = -2.6257395
nelat = 47.8359431, nelng = -0.9466615
```
Records outside this box are excluded (silent discard — not an error per spec assumptions).
Records **exactly on the boundary** are included (`>=`/`<=` comparison).

| Column | Type | Source | Transformation |
|--------|------|--------|----------------|
| `observation_id` | BIGINT | staging | Pass-through |
| `created_at_utc` | TIMESTAMP | staging | Pass-through |
| `observed_on` | DATE | staging | Pass-through |
| `latitude` | DOUBLE | staging | Pass-through (already validated in bbox filter) |
| `longitude` | DOUBLE | staging | Pass-through |
| `positional_accuracy_m` | INT | staging | Pass-through |
| `quality_grade` | VARCHAR | staging | Pass-through |
| `is_research_grade` | BOOLEAN | `quality_grade` | `quality_grade = 'research'` (FR-007) |
| `observation_period` | VARCHAR | `created_at_utc` | Hour-based classification (FR-006) |
| `taxon_id` | BIGINT | staging | Pass-through |
| `taxon_scientific_name` | VARCHAR | staging | Pass-through |
| `taxon_common_name` | VARCHAR | staging | Pass-through |
| `taxon_rank` | VARCHAR | staging | Pass-through |
| `taxon_threatened` | BOOLEAN | staging | Pass-through |
| `user_id` | BIGINT | staging | Pass-through |
| `user_login` | VARCHAR | staging | Pass-through |
| `user_display_name` | VARCHAR | staging | Pass-through |
| `observed_year` | INT | `observed_on` | `YEAR(observed_on)` — for fact partitioning |
| `observed_month` | INT | `observed_on` | `MONTH(observed_on)` — for fact partitioning |

**`observation_period` classification** (FR-006):
| Hour (UTC, local Paris time offset applied in staging) | Period |
|-------------------------------------------------------|--------|
| 00:00 – 05:59 | Madrugada |
| 06:00 – 11:59 | Mañana |
| 12:00 – 17:59 | Tarde |
| 18:00 – 23:59 | Noche |

Note: classification based on local hour (Paris time = UTC+1/+2) — convert `created_at_utc`
to `Europe/Paris` before bucketing.

**dbt tests**:
- `observation_id`: `unique`, `not_null`
- `is_research_grade`: `not_null`
- `observation_period`: `accepted_values: [Madrugada, Mañana, Tarde, Noche]`
- Custom singular test: `assert_observations_within_nantes_bbox.sql`

---

## Marts Layer (Star Schema)

### `fct_observations` (Fact Table)

**Purpose**: Central fact table for Power BI analytical queries. One row per valid bird
observation within Greater Nantes.

**Materialization**: `incremental` (`insert_overwrite`, partitioned by `(year, month)`)

**Grain**: One row per `observation_id`

| Column | Type | FK | Notes |
|--------|------|----|-------|
| `observation_id` | BIGINT | — | PK; surrogate key |
| `species_key` | BIGINT | `dim_species.species_key` | FK |
| `user_key` | BIGINT | `dim_users.user_key` | FK |
| `date_key` | DATE | `dim_date.date_key` | FK |
| `latitude` | DOUBLE | — | WGS84 |
| `longitude` | DOUBLE | — | WGS84 |
| `positional_accuracy_m` | INT | — | Nullable |
| `quality_grade` | VARCHAR | — | `research`/`needs_id`/`casual` |
| `is_research_grade` | BOOLEAN | — | FR-007 |
| `observation_period` | VARCHAR | — | FR-006 |
| `created_at_utc` | TIMESTAMP | — | Original submission time |
| `year` | INT | — | Partition key |
| `month` | INT | — | Partition key |

**Incremental filter**: `WHERE observed_on > (SELECT MAX(date_key) FROM {{ this }})`

**dbt tests**:
- `observation_id`: `unique`, `not_null`
- `species_key`: `not_null`, `relationships` → `dim_species.species_key`
- `user_key`: `not_null`, `relationships` → `dim_users.user_key`
- `date_key`: `not_null`, `relationships` → `dim_date.date_key`
- `quality_grade`: `accepted_values`
- `is_research_grade`: `not_null`

---

### `dim_species` (Species / Taxon Dimension)

**Purpose**: One row per unique taxon observed. Slowly-changing dimension (SCD Type 1 —
overwrite on re-run).

**Materialization**: `table`

**Grain**: One row per `taxon_id`

| Column | Type | Notes |
|--------|------|-------|
| `species_key` | BIGINT | PK; surrogate = `taxon_id` |
| `taxon_id` | BIGINT | iNaturalist taxon ID |
| `scientific_name` | VARCHAR | Latin binomial |
| `common_name` | VARCHAR | Nullable (absent for uncommon taxa) |
| `taxon_rank` | VARCHAR | e.g., `species`, `subspecies`, `genus` |
| `is_threatened` | BOOLEAN | iNaturalist threatened flag |

**dbt tests**:
- `species_key`: `unique`, `not_null`
- `taxon_id`: `unique`, `not_null`
- `scientific_name`: `not_null`

---

### `dim_users` (Observer / User Dimension)

**Purpose**: One row per unique citizen scientist observer. SCD Type 1.

**Materialization**: `table`

**Grain**: One row per `user_id`

| Column | Type | Notes |
|--------|------|-------|
| `user_key` | BIGINT | PK; surrogate = `user_id` |
| `user_id` | BIGINT | iNaturalist user ID |
| `login` | VARCHAR | iNaturalist username |
| `display_name` | VARCHAR | Full display name; nullable |

**dbt tests**:
- `user_key`: `unique`, `not_null`
- `user_id`: `unique`, `not_null`
- `login`: `not_null`

---

### `dim_date` (Calendar Dimension)

**Purpose**: Continuous calendar spine covering the full range of observation dates, enriched
with biological seasonality. Generated by dbt (no source dependency).

**Materialization**: `table`

**Grain**: One row per calendar day

**Date range**: Derived from `MIN(observed_on)` to `MAX(observed_on)` in
`int_observations__geospatial_enriched`, extended by ±30 days as buffer (FR-011).

| Column | Type | Notes |
|--------|------|-------|
| `date_key` | DATE | PK |
| `year` | INT | Calendar year |
| `month` | INT | Month number (1–12) |
| `month_name` | VARCHAR | e.g., `January` |
| `quarter` | INT | 1–4 |
| `day_of_week` | INT | 1 (Mon) – 7 (Sun) ISO |
| `day_name` | VARCHAR | e.g., `Monday` |
| `week_of_year` | INT | ISO week number |
| `is_weekend` | BOOLEAN | `day_of_week IN (6, 7)` |
| `biological_season` | VARCHAR | FR-011; see table below |

**Biological season mapping** (Northern Hemisphere, Greater Nantes latitude):
| Month | Season |
|-------|--------|
| March, April, May | Primavera |
| June, July, August | Verano |
| September, October, November | Otoño |
| December, January, February | Invierno |

**Edge case**: Observations with `observed_on` before `MIN(dim_date.date_key)` — not possible
if date range is generated after staging is populated. If a backfill introduces earlier dates,
`dim_date` must be regenerated with `--full-refresh`.

**dbt tests**:
- `date_key`: `unique`, `not_null`
- `biological_season`: `accepted_values: [Primavera, Verano, Otoño, Invierno]`

---

## Entity Relationship Diagram

```
fct_observations
  ├── species_key ──► dim_species.species_key
  ├── user_key ──────► dim_users.user_key
  └── date_key ──────► dim_date.date_key
```

---

## Validation Rules Summary

| Rule | Enforced by | Blocks promotion? |
|------|-------------|-------------------|
| `observation_id` unique + non-null | dbt `unique` + `not_null` | Yes (SC-004) |
| All coordinates within Nantes bbox | Custom singular SQL test | Yes |
| `quality_grade` ∈ {research, needs_id, casual} | `accepted_values` | Yes |
| FK integrity (fct → all dims) | `relationships` test | Yes |
| `dim_date` covers all `observed_on` | `relationships` on `date_key` | Yes |
| `observation_period` ∈ 4 valid values | `accepted_values` | Yes |
