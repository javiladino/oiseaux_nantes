# Contract: dbt Model Interfaces

**Feature**: `001-nantes-birds-pipeline` | **Date**: 2026-10-10

This document defines the public interface of each dbt model layer — what columns downstream
consumers (other models, Power BI) can rely on. Changes to these contracts require a PR review.

---

## Staging → Intermediate Contract

**Producer**: `stg_inaturalist__observations`
**Consumer**: `int_observations__geospatial_enriched`

The intermediate model depends on these columns from staging:

| Column | Type | Guarantee |
|--------|------|-----------|
| `observation_id` | BIGINT | Unique, non-null |
| `created_at_utc` | TIMESTAMP | UTC-normalized, non-null |
| `observed_on` | DATE | Non-null |
| `latitude` | DOUBLE | Non-null; raw value (no bbox filter yet) |
| `longitude` | DOUBLE | Non-null; raw value |
| `quality_grade` | VARCHAR | One of: `research`, `needs_id`, `casual` |
| `taxon_id` | BIGINT | Non-null |
| `taxon_scientific_name` | VARCHAR | Non-null |
| `taxon_common_name` | VARCHAR | Nullable |
| `taxon_rank` | VARCHAR | Non-null |
| `taxon_threatened` | BOOLEAN | Non-null |
| `user_id` | BIGINT | Non-null |
| `user_login` | VARCHAR | Non-null |
| `user_display_name` | VARCHAR | Nullable |

---

## Intermediate → Marts Contract

**Producer**: `int_observations__geospatial_enriched`
**Consumers**: `fct_observations`, `dim_species`, `dim_users`, `dim_date`

The intermediate model guarantees these columns to marts:

| Column | Type | Guarantee |
|--------|------|-----------|
| `observation_id` | BIGINT | Unique, non-null; within Nantes bbox |
| `created_at_utc` | TIMESTAMP | Non-null |
| `observed_on` | DATE | Non-null |
| `latitude` | DOUBLE | Non-null; `46.86 ≤ lat ≤ 47.84` |
| `longitude` | DOUBLE | Non-null; `-2.63 ≤ lng ≤ -0.95` |
| `quality_grade` | VARCHAR | One of: `research`, `needs_id`, `casual` |
| `is_research_grade` | BOOLEAN | Non-null |
| `observation_period` | VARCHAR | One of: `Madrugada`, `Mañana`, `Tarde`, `Noche` |
| `taxon_id` | BIGINT | Non-null |
| `taxon_scientific_name` | VARCHAR | Non-null |
| `taxon_common_name` | VARCHAR | Nullable |
| `taxon_rank` | VARCHAR | Non-null |
| `taxon_threatened` | BOOLEAN | Non-null |
| `user_id` | BIGINT | Non-null |
| `user_login` | VARCHAR | Non-null |
| `user_display_name` | VARCHAR | Nullable |
| `observed_year` | INT | Non-null |
| `observed_month` | INT | Non-null |

---

## Marts → Power BI Contract

**Producer**: `marts/` layer
**Consumer**: Power BI Desktop / Service (Import mode)

Power BI MUST reference only these tables and columns:

### `fct_observations`

| Column | Type | Description |
|--------|------|-------------|
| `observation_id` | BIGINT | PK; unique observation identifier |
| `species_key` | BIGINT | FK → `dim_species` |
| `user_key` | BIGINT | FK → `dim_users` |
| `date_key` | DATE | FK → `dim_date` |
| `latitude` | DOUBLE | WGS84 latitude |
| `longitude` | DOUBLE | WGS84 longitude |
| `quality_grade` | VARCHAR | `research`/`needs_id`/`casual` |
| `is_research_grade` | BOOLEAN | True if research grade |
| `observation_period` | VARCHAR | Time-of-day period |

### `dim_species`

| Column | Type | Description |
|--------|------|-------------|
| `species_key` | BIGINT | PK |
| `scientific_name` | VARCHAR | Latin binomial |
| `common_name` | VARCHAR | English/French name (nullable) |
| `taxon_rank` | VARCHAR | Taxonomic rank |
| `is_threatened` | BOOLEAN | Threatened status |

### `dim_users`

| Column | Type | Description |
|--------|------|-------------|
| `user_key` | BIGINT | PK |
| `login` | VARCHAR | iNaturalist username |
| `display_name` | VARCHAR | Full name (nullable) |

### `dim_date`

| Column | Type | Description |
|--------|------|-------------|
| `date_key` | DATE | PK |
| `year` | INT | Calendar year |
| `month` | INT | Month (1–12) |
| `month_name` | VARCHAR | Month name |
| `quarter` | INT | Quarter (1–4) |
| `day_of_week` | INT | ISO day (1=Mon, 7=Sun) |
| `day_name` | VARCHAR | Day name |
| `is_weekend` | BOOLEAN | |
| `biological_season` | VARCHAR | `Primavera`/`Verano`/`Otoño`/`Invierno` |

### Relationships (Power BI Model View)

```
fct_observations[species_key] → dim_species[species_key]   (Many-to-One)
fct_observations[user_key]    → dim_users[user_key]        (Many-to-One)
fct_observations[date_key]    → dim_date[date_key]         (Many-to-One)
```

### Power BI Measures (FR-012)

| Measure | DAX | Description |
|---------|-----|-------------|
| Total Observations | `COUNTROWS(fct_observations)` | Count of all valid observations |
| Distinct Species | `DISTINCTCOUNT(fct_observations[species_key])` | Unique species count |
| Research Grade % | `DIVIDE(CALCULATE(COUNTROWS(fct_observations), fct_observations[is_research_grade]), COUNTROWS(fct_observations))` | % research grade |

---

## Breaking Change Policy

Any removal or rename of a column in this contract requires:
1. A PR with constitution compliance review
2. Updated Power BI dataset and report before merging
3. A comment in the model `.yml` file explaining the migration path
