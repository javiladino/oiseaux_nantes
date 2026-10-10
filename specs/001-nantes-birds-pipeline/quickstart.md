# Quickstart Validation Guide: Nantes Birds Pipeline

**Feature**: `001-nantes-birds-pipeline` | **Date**: 2026-10-10

This guide documents runnable validation scenarios that prove each pipeline layer works
end-to-end. It is not an implementation guide — for model definitions see [data-model.md](data-model.md),
for API details see [contracts/inaturalist-api.md](contracts/inaturalist-api.md).

---

## Prerequisites

| Prerequisite | Check |
|-------------|-------|
| AWS CLI configured (`eu-west-3`) | `aws sts get-caller-identity` |
| S3 bucket exists with correct prefix | `aws s3 ls s3://{bucket}/raw/inaturalist/` |
| SSM parameter created (or absent for first run) | `aws ssm get-parameter --name /birds-pipeline/last_successful_run_date` |
| Athena workgroup + Glue databases (`birds_raw`, `birds_dbt`) exist | AWS Console / Athena |
| dbt project installed and profiles.yml configured | `dbt debug` |
| Python 3.11+ and Lambda dependencies installed locally | `python --version` |

---

## Scenario 1: First-Run Ingestion (Story 1, AC-1)

**What it proves**: FR-001/002/003, SC-001, SC-006 (first run baseline)

### Steps

```bash
# 1. Confirm no watermark exists (first run)
aws ssm get-parameter --name /birds-pipeline/last_successful_run_date
# Expected: ParameterNotFound error

# 2. Invoke Lambda (locally or via AWS Console test event)
aws lambda invoke \
  --function-name birds-inaturalist-ingestion \
  --payload '{}' \
  response.json
cat response.json
# Expected: {"statusCode": 200, "body": "Ingested N observations"}

# 3. Verify S3 files created under current year/month partition
aws s3 ls s3://{bucket}/raw/inaturalist/observations/ --recursive
# Expected: files under year=YYYY/month=MM/

# 4. Spot-check one file contains valid JSON observations
aws s3 cp s3://{bucket}/raw/inaturalist/observations/year=.../month=.../{file}.json - | head -1 | python3 -m json.tool
# Expected: well-formed JSON with id, created_at, location, taxon, user fields

# 5. Confirm watermark was updated
aws ssm get-parameter --name /birds-pipeline/last_successful_run_date
# Expected: {"Parameter": {"Value": "YYYY-MM-DDTHH:MM:SS"}}
```

### Expected Outcome
- One or more NDJSON files present in S3 under the correct partition
- Each line is a valid JSON observation object
- SSM parameter holds today's run timestamp
- No duplicate `id` values across all files (spot-check)

---

## Scenario 2: Incremental Run — No Duplicates (Story 1, AC-2/3/4)

**What it proves**: FR-002/014, SC-002/006

### Steps

```bash
# 1. Record the current observation count in S3
aws s3 ls s3://{bucket}/raw/inaturalist/observations/ --recursive | wc -l
# Note: file_count_before

# 2. Invoke Lambda again (same day — should find 0 or few new observations)
aws lambda invoke \
  --function-name birds-inaturalist-ingestion \
  --payload '{}' \
  response2.json
cat response2.json

# 3. Verify file count did not change (if 0 new obs) or increased by exactly new obs count
aws s3 ls s3://{bucket}/raw/inaturalist/observations/ --recursive | wc -l
# Expected: file_count_before (if 0 new) or file_count_before + 1

# 4. Verify observation IDs across all files are unique (run Athena query):
# SELECT COUNT(*), COUNT(DISTINCT id) FROM raw_inaturalist.observations
# Expected: COUNT(*) = COUNT(DISTINCT id)
```

### Expected Outcome
- No new files if no new observations since last run
- Re-running produces same final state (idempotent)
- No duplicate `id` values across partitions

---

## Scenario 3: dbt Staging Model Validation (Story 2, AC-1)

**What it proves**: FR-004, FR-008/010/015, SC-004

### Steps

```bash
# 1. Register external raw table (run once after raw data exists)
cd dbt_birds
dbt run-operation stage_external_sources

# 2. Run staging model
dbt run --select stg_inaturalist__observations

# 3. Run staging tests
dbt test --select stg_inaturalist__observations
# Expected: All tests pass (0 failures, 0 warnings)

# 4. Verify flattening in Athena console or dbt:
# SELECT observation_id, latitude, longitude, taxon_scientific_name, user_login
# FROM birds_dbt.stg_inaturalist__observations LIMIT 5
# Expected: All columns populated (latitude/longitude as DOUBLE, not "lat,lng" string)
```

### Expected Outcome
- `dbt test` reports 0 failures
- `observation_id` is unique and non-null
- `latitude`/`longitude` are separate DOUBLE columns
- `quality_grade` ∈ {research, needs_id, casual}

---

## Scenario 4: Intermediate Model — Bounding Box Validation (Story 2, AC-2)

**What it proves**: FR-005/006/007, SC-003

### Steps

```bash
# 1. Run intermediate model
dbt run --select int_observations__geospatial_enriched

# 2. Run tests including custom bbox test
dbt test --select int_observations__geospatial_enriched
# Expected: All tests pass including assert_observations_within_nantes_bbox

# 3. Verify bbox containment in Athena:
# SELECT MIN(latitude), MAX(latitude), MIN(longitude), MAX(longitude)
# FROM birds_dbt.int_observations__geospatial_enriched
# Expected: lat ∈ [46.86, 47.84], lng ∈ [-2.63, -0.95]

# 4. Verify observation_period distribution:
# SELECT observation_period, COUNT(*) FROM birds_dbt.int_observations__geospatial_enriched
# GROUP BY observation_period ORDER BY 2 DESC
# Expected: 4 rows, all periods present (Madrugada/Mañana/Tarde/Noche)

# 5. Verify is_research_grade:
# SELECT is_research_grade, quality_grade, COUNT(*) 
# FROM birds_dbt.int_observations__geospatial_enriched
# GROUP BY 1, 2
# Expected: is_research_grade=true only where quality_grade='research'
```

### Expected Outcome
- 0 records outside Nantes bounding box
- All 4 `observation_period` values present
- `is_research_grade` correctly derived from `quality_grade`

---

## Scenario 5: Full Mart Layer — Star Schema Integrity (Story 2, AC-3/4/5)

**What it proves**: FR-008/009/011/012, SC-002/004

### Steps

```bash
# 1. Run full dbt DAG (first run: must use --full-refresh for incremental models)
dbt run --full-refresh
# Or for incremental runs after first:
dbt run

# 2. Run all tests
dbt test
# Expected: 0 failures across all models

# 3. Verify primary key uniqueness in Athena:
# SELECT COUNT(*), COUNT(DISTINCT observation_id) FROM birds_dbt.fct_observations
# Expected: both counts equal

# 4. Verify referential integrity (no orphan FKs):
# SELECT COUNT(*) FROM birds_dbt.fct_observations f
# LEFT JOIN birds_dbt.dim_species s ON f.species_key = s.species_key
# WHERE s.species_key IS NULL
# Expected: 0

# Repeat for dim_users and dim_date

# 5. Verify dim_date covers full observation range:
# SELECT MIN(date_key), MAX(date_key) FROM birds_dbt.dim_date
# vs
# SELECT MIN(observed_on), MAX(observed_on) FROM birds_dbt.fct_observations
# Expected: dim_date range ⊇ fct_observations observed_on range

# 6. Verify the 3 analytical metrics (FR-012):
# SELECT
#   COUNT(*) AS total_observations,
#   COUNT(DISTINCT species_key) AS distinct_species,
#   SUM(CASE WHEN is_research_grade THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS research_grade_pct
# FROM birds_dbt.fct_observations
# Expected: 3 numeric values, research_grade_pct between 0 and 100
```

### Expected Outcome
- `dbt test` passes 100% across all mart models
- No duplicate `observation_id` in `fct_observations`
- All FK relationships intact
- `dim_date` fully covers observation date range
- 3 analytical metrics return valid values

---

## Scenario 6: Power BI End-to-End Refresh (Story 3)

**What it proves**: FR-012/013, SC-001/005

### Steps

1. Open Power BI Desktop
2. Connect via ODBC (Amazon Athena driver):
   - Server: `athena.eu-west-3.amazonaws.com`
   - Database: `birds_dbt`
3. Import these tables: `fct_observations`, `dim_species`, `dim_users`, `dim_date`
4. Set relationships in Model view (see [contracts/dbt-models.md](contracts/dbt-models.md))
5. Create the 3 required visuals:
   - **Map visual**: Plot `latitude`/`longitude` from `fct_observations`; filter slicer on `dim_species[common_name]`
   - **Seasonal trend**: Line/bar chart of `COUNT(observation_id)` by `dim_date[month_name]` coloured by `dim_date[biological_season]`
   - **Ranking table**: `dim_species[common_name]`, `COUNT(observation_id)` DESC + `dim_users[login]`, `COUNT(observation_id)` DESC
6. Publish to Power BI Service
7. Configure scheduled refresh (daily, time after Lambda EventBridge execution)

### Expected Outcome
- Map renders geolocated bird observations within Nantes boundary
- Seasonal trend shows monthly counts with `Primavera`/`Verano`/`Otoño`/`Invierno` colouring
- Ranking table lists top species and top observers
- After pipeline re-run, dataset refresh pulls new data without manual intervention (SC-001)

---

## Scenario 7: Idempotency Under Failure (SC-006)

**What it proves**: FR-003/014, SC-006

### Steps

```bash
# 1. Simulate partial Lambda failure (set Lambda timeout to 5s — shorter than normal run)
# Then invoke Lambda → it should fail mid-pagination

# 2. Verify SSM watermark was NOT updated
aws ssm get-parameter --name /birds-pipeline/last_successful_run_date
# Expected: same value as before the failed run

# 3. Restore normal Lambda timeout (180s)
# Re-invoke Lambda — it should start from the same watermark and complete normally

# 4. Check for duplicate observation IDs in S3/Athena
# (Same Athena query as Scenario 2, Step 4)
# Expected: COUNT(*) = COUNT(DISTINCT id)
```

### Expected Outcome
- Failed run leaves watermark unchanged
- Re-run completes successfully from the same watermark
- No duplicate `observation_id` values in any layer

---

## CI Validation (GitHub Actions)

Every PR touching `dbt_birds/` triggers:

```yaml
# .github/workflows/dbt_ci.yml
- run: dbt compile
- run: dbt test --select state:modified+
```

A failed `dbt test` must block the PR merge (constitution III). Check the workflow status
badge or Actions tab before merging.
