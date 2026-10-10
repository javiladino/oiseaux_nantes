---

description: "Task list for Nantes Birds Biodiversity Pipeline implementation"
---

# Tasks: Nantes Birds Biodiversity Pipeline

**Input**: Design documents from `/specs/001-nantes-birds-pipeline/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: Included — Lambda unit tests (pytest + moto) and dbt schema tests are explicitly specified in plan.md.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths included in each task description

## Path Conventions

Single-repository layout:
- `ingestion/` — Lambda Python package
- `tests/unit/` / `tests/integration/` — Python tests
- `dbt_birds/` — dbt project root
- `.github/workflows/` — GitHub Actions
- `reports/` — Power BI artifacts
- `docs/` — supplementary documentation

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project directory scaffolding and dependency initialization

- [ ] T001 Create project directory tree: `ingestion/`, `tests/unit/`, `tests/integration/`, `dbt_birds/models/sources/`, `dbt_birds/models/staging/`, `dbt_birds/models/intermediate/`, `dbt_birds/models/marts/`, `dbt_birds/tests/`, `reports/`, `docs/`
- [ ] T002 [P] Create `ingestion/requirements.txt` with `requests>=2.31` and `boto3>=1.34`
- [ ] T003 [P] Create `tests/requirements-dev.txt` with `pytest>=7.4`, `moto[s3,ssm]>=4.2`, and `boto3>=1.34`
- [ ] T004 [P] Create `.gitignore` covering Python (`__pycache__/`, `*.pyc`, `.env`) and dbt (`dbt_birds/target/`, `dbt_birds/dbt_packages/`, `dbt_birds/logs/`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: dbt project configuration and pytest fixtures — required before any user story implementation

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T005 Create `dbt_birds/dbt_project.yml` — set `name: birds_dbt`, configure model materializations: `staging: {+materialized: view}`, `intermediate: {+materialized: view}`, `marts: {+materialized: table}`; set default `+format: parquet` and `+write_compression: snappy` under `marts`
- [ ] T006 [P] Create `dbt_birds/profiles.yml` — Athena connection: `type: athena`, `region_name: eu-west-3`, `database: awsdatacatalog`, `schema: birds_dbt`, `threads: 4`, `s3_staging_dir: s3://{bucket}/athena-results/`, `s3_data_dir: s3://{bucket}/processed/`
- [ ] T007 Create `dbt_birds/models/sources/sources.yml` — define `raw_inaturalist` source (schema: `birds_raw`, table: `observations`, external: location `s3://{bucket}/raw/inaturalist/observations/`, SerDe: `org.openx.data.jsonserde.JsonSerDe`, partitions: `year STRING`, `month STRING`)
- [ ] T008 [P] Create `tests/conftest.py` — pytest fixtures: `aws_credentials` (sets dummy env vars for moto), `s3_bucket` (moto S3 bucket named `test-birds-bucket`), `ssm_client` (moto SSM in `eu-west-3`), `ssm_param_name` constant `/birds-pipeline/last_successful_run_date`
- [ ] T009 [P] Create `dbt_birds/packages.yml` — declare `dbt-labs/dbt_utils` and `dbt-labs/dbt_external_tables` packages; run `dbt deps` to install

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 — Incremental Ingestion (Priority: P1) 🎯 MVP

**Goal**: Lambda fetches only new Nantes bird observations from iNaturalist since the last successful run, writes raw NDJSON to S3, and updates the watermark atomically.

**Independent Test**: Invoke Lambda locally → verify new NDJSON files appear under `s3://{bucket}/raw/inaturalist/observations/year={YYYY}/month={MM}/` → re-invoke → confirm no duplicate `id` values and SSM watermark is updated.

### Implementation for User Story 1

- [ ] T010 [P] [US1] Implement `ingestion/inaturalist_client.py` — `fetch_observations(watermark: str | None) -> list[dict]`: paginate `GET https://api.inaturalist.org/v1/observations` using `id_above` cursor (per_page=200, order_by=id, order=asc); params: `taxon_id=3`, `swlat=46.8600781`, `swlng=-2.6257395`, `nelat=47.8359431`, `nelng=-0.9466615`, `created_d1=watermark` (omit on first run); headers: `User-Agent: oiseaux-nantes-pipeline/1.0`; sleep 1s between pages; exponential backoff on 429/500/503 (max 3 retries); stop when `len(results) < per_page`
- [ ] T011 [P] [US1] Implement `ingestion/s3_writer.py` — `write_batch(s3_client, bucket: str, observations: list[dict], run_ts: datetime) -> str`: writes NDJSON to `s3://{bucket}/raw/inaturalist/observations/year={YYYY}/month={MM}/{timestamp}.json` (UTF-8, one raw JSON object per line per `results[]` item, no transformation); returns the S3 key written
- [ ] T012 [P] [US1] Implement `ingestion/ssm_watermark.py` — `get_watermark(ssm_client, param_name: str) -> str | None`: returns SSM String value or `None` on `ParameterNotFound`; `put_watermark(ssm_client, param_name: str, value: str) -> None`: puts with `Type="String"`, `Overwrite=True`; param name: `/birds-pipeline/last_successful_run_date`
- [ ] T013 [US1] Implement `ingestion/handler.py` — Lambda entry point `lambda_handler(event, context)`: (1) `get_watermark()`, (2) `fetch_observations(watermark)`, (3) if observations > 0: `write_batch()` for each page batch, (4) `put_watermark(run_ts)` **only** after all S3 writes succeed; if 0 new observations: skip S3 write and watermark update; return `{"statusCode": 200, "body": f"Ingested {N} observations"}`; watermark format: ISO 8601 datetime (`YYYY-MM-DDTHH:MM:SS`)

### Tests for User Story 1

- [ ] T014 [P] [US1] Write `tests/unit/test_inaturalist_client.py` — moto tests: first-run with no watermark fetches all observations; incremental run passes `created_d1`; `id_above` cursor advances correctly across pages; zero-results response returns empty list; 429 response triggers exponential backoff and retries ≤ 3; max retries exceeded raises exception
- [ ] T015 [P] [US1] Write `tests/unit/test_s3_writer.py` — moto S3 tests: output key matches `year={YYYY}/month={MM}/{timestamp}.json` pattern; file content is valid NDJSON (each line parses as JSON); multiple batches written to separate files; UTF-8 encoding preserved
- [ ] T016 [P] [US1] Write `tests/unit/test_ssm_watermark.py` — moto SSM tests: `get_watermark()` returns `None` when parameter does not exist; returns correct string when parameter exists; `put_watermark()` creates parameter on first call; `put_watermark()` overwrites on subsequent calls
- [ ] T017 [US1] Write `tests/integration/test_ingestion_e2e.py` — live iNaturalist API test (read-only, no side effects): call `fetch_observations(watermark=None)` with page limit of 1; assert response contains `id`, `created_at`, `location`, `taxon`, `user` fields; assert `quality_grade` is one of `research`, `needs_id`, `casual`; mark with `@pytest.mark.integration` for selective execution

**Checkpoint**: User Story 1 fully functional — ingestion pipeline works independently

---

## Phase 4: User Story 2 — dbt Medallion Transformation (Priority: P2)

**Goal**: dbt DAG transforms raw JSON through staging → intermediate → marts, producing a validated star schema (`fct_observations`, `dim_species`, `dim_users`, `dim_date`) with all dbt schema tests passing.

**Independent Test**: `dbt run --full-refresh && dbt test` against a populated raw layer returns 0 failures across all models; `fct_observations` has no duplicate `observation_id`; all FK relationships intact.

### Implementation for User Story 2

- [ ] T018 [P] [US2] Create `dbt_birds/models/staging/stg_inaturalist__observations.sql` — materialized=view; `CAST(id AS BIGINT) AS observation_id`; parse `created_at` → `TIMESTAMP` UTC as `created_at_utc`; `CAST(split_part(location, ',', 1) AS DOUBLE) AS latitude`; `CAST(split_part(location, ',', 2) AS DOUBLE) AS longitude`; flatten `taxon.id` → `taxon_id BIGINT`, `taxon.name` → `taxon_scientific_name`, `taxon.preferred_common_name` → `taxon_common_name` (nullable), `taxon.rank` → `taxon_rank`, `taxon.threatened` → `taxon_threatened BOOLEAN`; flatten `user.id` → `user_id BIGINT`, `user.login` → `user_login`, `user.name` → `user_display_name` (nullable); dedup: `ROW_NUMBER() OVER (PARTITION BY observation_id ORDER BY created_at_utc DESC) = 1`; pass `_ingested_year`, `_ingested_month` partition columns
- [ ] T019 [P] [US2] Create `dbt_birds/models/staging/stg_inaturalist__observations.yml` — document all 17 columns with description; tests: `observation_id` (unique, not_null), `quality_grade` (accepted_values: [research, needs_id, casual]), `latitude` (not_null), `longitude` (not_null), `taxon_id` (not_null), `user_id` (not_null)
- [ ] T020 [US2] Create `dbt_birds/models/intermediate/int_observations__geospatial_enriched.sql` — materialized=view; FROM `stg_inaturalist__observations`; bbox filter: `latitude BETWEEN 46.8600781 AND 47.8359431 AND longitude BETWEEN -2.6257395 AND -0.9466615` (boundary inclusive, ≥/≤); `(quality_grade = 'research') AS is_research_grade`; convert `created_at_utc` to `Europe/Paris` hour then CASE: 0-5→'Madrugada', 6-11→'Mañana', 12-17→'Tarde', 18-23→'Noche' AS `observation_period`; `YEAR(observed_on) AS observed_year`; `MONTH(observed_on) AS observed_month`; pass all staging columns through
- [ ] T021 [P] [US2] Create `dbt_birds/models/intermediate/int_observations__geospatial_enriched.yml` — document all columns; tests: `observation_id` (unique, not_null), `is_research_grade` (not_null), `observation_period` (accepted_values: [Madrugada, Mañana, Tarde, Noche]); reference custom singular test `assert_observations_within_nantes_bbox`
- [ ] T022 [P] [US2] Create `dbt_birds/tests/assert_observations_within_nantes_bbox.sql` — singular test: `SELECT * FROM {{ ref('int_observations__geospatial_enriched') }} WHERE latitude < 46.8600781 OR latitude > 47.8359431 OR longitude < -2.6257395 OR longitude > -0.9466615`; must return 0 rows to pass (SC-003)
- [ ] T023 [P] [US2] Create `dbt_birds/models/marts/dim_species.sql` — materialized=table; `SELECT DISTINCT taxon_id AS species_key, taxon_id, taxon_scientific_name AS scientific_name, taxon_common_name AS common_name, taxon_rank, taxon_threatened AS is_threatened FROM {{ ref('int_observations__geospatial_enriched') }}`
- [ ] T024 [P] [US2] Create `dbt_birds/models/marts/dim_species.yml` — document all 6 columns (note `common_name` nullable); tests: `species_key` (unique, not_null), `taxon_id` (unique, not_null), `scientific_name` (not_null)
- [ ] T025 [P] [US2] Create `dbt_birds/models/marts/dim_users.sql` — materialized=table; `SELECT DISTINCT user_id AS user_key, user_id, user_login AS login, user_display_name AS display_name FROM {{ ref('int_observations__geospatial_enriched') }}`
- [ ] T026 [P] [US2] Create `dbt_birds/models/marts/dim_users.yml` — document all 4 columns (note `display_name` nullable); tests: `user_key` (unique, not_null), `user_id` (unique, not_null), `login` (not_null)
- [ ] T027 [P] [US2] Create `dbt_birds/models/marts/dim_date.sql` — materialized=table; generate date spine: `MIN(observed_on) - INTERVAL '30' DAY` to `MAX(observed_on) + INTERVAL '30' DAY` from `int_observations__geospatial_enriched`; columns: `date_key DATE`, `year INT`, `month INT (1-12)`, `month_name VARCHAR`, `quarter INT (1-4 = CEIL(month/3.0))`, `day_of_week INT (ISO 1=Mon–7=Sun)`, `day_name VARCHAR`, `week_of_year INT`, `is_weekend BOOLEAN (day_of_week IN (6,7))`, `biological_season VARCHAR (month 3-5→'Primavera', 6-8→'Verano', 9-11→'Otoño', 12,1,2→'Invierno')`
- [ ] T028 [P] [US2] Create `dbt_birds/models/marts/dim_date.yml` — document all 10 columns; tests: `date_key` (unique, not_null), `biological_season` (accepted_values: [Primavera, Verano, Otoño, Invierno])
- [ ] T029 [US2] Create `dbt_birds/models/marts/fct_observations.sql` — config: `materialized=incremental, incremental_strategy=insert_overwrite, partitioned_by=['year','month'], format='parquet', write_compression='snappy'`; JOIN `int_observations__geospatial_enriched` with `dim_species` (ON `taxon_id = species_key`), `dim_users` (ON `user_id = user_key`), `dim_date` (ON `observed_on = date_key`); SELECT `observation_id, species_key, user_key, date_key, latitude, longitude, positional_accuracy_m, quality_grade, is_research_grade, observation_period, created_at_utc, observed_year AS year, observed_month AS month`; incremental filter: `WHERE observed_on > (SELECT MAX(date_key) FROM {{ this }})`
- [ ] T030 [P] [US2] Create `dbt_birds/models/marts/fct_observations.yml` — document all 13 columns; tests: `observation_id` (unique, not_null), `species_key` (not_null, relationships→dim_species.species_key), `user_key` (not_null, relationships→dim_users.user_key), `date_key` (not_null, relationships→dim_date.date_key), `quality_grade` (accepted_values: [research, needs_id, casual]), `is_research_grade` (not_null)
- [ ] T031 [US2] Complete `dbt_birds/.github/workflows/dbt_ci.yml` — trigger: `on: [pull_request]` for paths `dbt_birds/**`; steps: checkout, install `dbt-athena-community`, configure `profiles.yml` from GitHub secrets (`DBT_ATHENA_S3_STAGING_DIR`, `DBT_ATHENA_S3_DATA_DIR`), `dbt compile`, `dbt test --select state:modified+`; fail workflow on any dbt test failure (SC-004)

**Checkpoint**: User Story 2 fully functional — full dbt DAG produces validated star schema independently

---

## Phase 5: User Story 3 — Biodiversity Insights in Power BI (Priority: P3)

**Goal**: Power BI report connects to Athena marts in Import mode and renders three interactive analytics visuals: geospatial map, seasonal trend, and ranking table.

**Independent Test**: Connect Power BI Desktop to Athena `birds_dbt` schema → import 4 mart tables → verify map renders geolocated observations, seasonal chart shows 4 biological seasons, ranking table lists top species and observers, and cross-filtering works across all visuals.

### Implementation for User Story 3

- [ ] T032 [P] [US3] Create `docs/powerbi-setup.md` — document ODBC connection steps: install Amazon Athena ODBC driver (64-bit Simba), create DSN pointing to `athena.eu-west-3.amazonaws.com`, database `birds_dbt`, configure AWS credentials; Power BI Desktop: Get Data → ODBC → select DSN → Import mode; tables: `fct_observations`, `dim_species`, `dim_users`, `dim_date`
- [ ] T033 [US3] Create `reports/nantes_birds.pbix` — Power BI report file: import 4 mart tables via Athena ODBC DSN; configure star schema relationships in Model view per `contracts/dbt-models.md`: `fct_observations[species_key]→dim_species[species_key]` (Many-to-One), `fct_observations[user_key]→dim_users[user_key]` (Many-to-One), `fct_observations[date_key]→dim_date[date_key]` (Many-to-One)
- [ ] T034 [P] [US3] Add geospatial map visual to `reports/nantes_birds.pbix` — map visual (ArcGIS Maps or built-in map): latitude from `fct_observations[latitude]`, longitude from `fct_observations[longitude]`; tooltip showing `dim_species[common_name]` and `quality_grade`; species filter slicer on `dim_species[common_name]` (FR-013)
- [ ] T035 [P] [US3] Add seasonal trend visual to `reports/nantes_birds.pbix` — clustered bar chart: X-axis `dim_date[month_name]`, Y-axis `COUNT(fct_observations[observation_id])`, legend coloured by `dim_date[biological_season]` (Primavera/Verano/Otoño/Invierno); date range slicer on `dim_date[date_key]`
- [ ] T036 [P] [US3] Add ranking table visual and DAX measures to `reports/nantes_birds.pbix` — table visual: `dim_species[common_name]` + `COUNT(observation_id)` DESC, `dim_users[login]` + `COUNT(observation_id)` DESC; add measures: `Total Observations = COUNTROWS(fct_observations)`, `Distinct Species = DISTINCTCOUNT(fct_observations[species_key])`, `Research Grade % = DIVIDE(CALCULATE(COUNTROWS(fct_observations), fct_observations[is_research_grade]=TRUE()), COUNTROWS(fct_observations))` (FR-012)
- [ ] T037 [US3] Publish `reports/nantes_birds.pbix` to Power BI Service — upload to workspace; configure dataset scheduled refresh (daily, time set after EventBridge Lambda cron trigger); verify all 3 visuals render correctly with real data and respond to cross-filtering; confirm refresh pulls new observations without manual intervention (SC-001, SC-005)

**Checkpoint**: User Story 3 fully functional — all analytical insights accessible without writing SQL

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Observability, scheduling, and validation across all user stories

- [ ] T038 [P] Configure CloudWatch Alarm on Lambda `birds-inaturalist-ingestion` error/timeout metric (threshold: ≥1 over 5 minutes) connected to an SNS topic that notifies pipeline owner by email (FR-016)
- [ ] T039 [P] Configure Amazon EventBridge daily cron rule targeting `birds-inaturalist-ingestion` Lambda (cron expression for daily execution, timed before Power BI scheduled refresh) — document cron expression and IAM permissions in `docs/infrastructure.md`
- [ ] T040 Run all 7 quickstart.md validation scenarios end-to-end and document pass/fail results in `docs/validation-results.md`: Scenario 1 (first-run ingestion), Scenario 2 (incremental no-duplicate), Scenario 3 (staging tests), Scenario 4 (bbox validation), Scenario 5 (full mart integrity), Scenario 6 (Power BI refresh), Scenario 7 (idempotency under failure)
- [ ] T041 [P] Review all dbt model `.yml` files — confirm every column across all 7 models has a `description` field and at least one test; add any missing documentation per constitution principle V

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — blocks all user stories
- **User Story 1 (Phase 3)**: Depends on Phase 2 — can start in parallel with Phase 4
- **User Story 2 (Phase 4)**: Depends on Phase 2 — can start in parallel with Phase 3
- **User Story 3 (Phase 5)**: Depends on Phase 4 completion (marts must be populated)
- **Polish (Phase 6)**: Depends on all prior phases complete

### User Story Dependencies

- **US1 (P1)**: Depends only on Foundational — no dependency on US2/US3
- **US2 (P2)**: Depends only on Foundational — requires populated raw layer for `dbt run`, but model code can be written in parallel with US1
- **US3 (P3)**: Depends on US2 mart layer being populated and validated

### Within Each User Story

- US1: T010, T011, T012 are parallel → T013 depends on all three → T014–T016 are parallel → T017 depends on T013
- US2: T018/T019 parallel → T020 depends on T018 → T021/T022 parallel with T020 → T023–T028 parallel → T029 depends on T023+T025+T027 → T030 parallel with T029 → T031 independent
- US3: T032 parallel → T033 depends on T032 → T034/T035/T036 parallel → T037 depends on T033–T036

---

## Parallel Execution Examples

### User Story 1 — Parallel Opportunities

```bash
# Parallel: implement the three Lambda modules simultaneously
Task T010: ingestion/inaturalist_client.py
Task T011: ingestion/s3_writer.py
Task T012: ingestion/ssm_watermark.py

# Parallel: write unit tests alongside each module
Task T014: tests/unit/test_inaturalist_client.py
Task T015: tests/unit/test_s3_writer.py
Task T016: tests/unit/test_ssm_watermark.py

# Sequential: handler after all modules complete
Task T013: ingestion/handler.py  (depends on T010+T011+T012)
```

### User Story 2 — Parallel Opportunities

```bash
# Parallel: staging SQL + staging YAML together
Task T018: stg_inaturalist__observations.sql
Task T019: stg_inaturalist__observations.yml

# Parallel: three dimension models after intermediate is done
Task T023: dim_species.sql      Task T024: dim_species.yml
Task T025: dim_users.sql        Task T026: dim_users.yml
Task T027: dim_date.sql         Task T028: dim_date.yml

# Sequential: fact table after all dims complete
Task T029: fct_observations.sql  (depends on T023+T025+T027)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 (T010–T017)
4. **STOP and VALIDATE**: invoke Lambda, check S3 files, verify SSM watermark, confirm no duplicates
5. US1 is independently deliverable and verifiable

### Incremental Delivery

1. Setup + Foundational → scaffold ready
2. US1 (Lambda ingestion) → raw S3 layer populated → **MVP demo**
3. US2 (dbt transformations) → star schema live in Athena → run `dbt test`
4. US3 (Power BI) → analytical dashboards live → stakeholder demo
5. Polish → alerting, scheduling, full end-to-end validation

### Parallel Team Strategy

With multiple developers after Phase 2 is complete:
- Developer A: User Story 1 (Lambda ingestion, Python)
- Developer B: User Story 2 (dbt models, SQL)
- Both stories complete independently; US3 begins when US2 marts are validated

---

## Notes

- **[P]** tasks operate on different files with no inter-dependencies — safe to run in parallel
- **[Story]** label enables traceability from task to acceptance criteria in spec.md
- Watermark must **never** be updated on partial S3 failure (constitution IV + FR-002)
- First `dbt run` on `fct_observations` requires `--full-refresh` (insert_overwrite needs partition creation)
- `dbt-external-tables` registration (`dbt run-operation stage_external_sources`) is a one-time step after raw data exists in S3 — document in quickstart.md
- Lambda IAM role must be scoped to `s3:PutObject` on target prefix only + `ssm:GetParameter`/`ssm:PutParameter` on the single watermark ARN — no wildcard ARNs (constitution IV)
- All mart models must carry `format='parquet'` + `write_compression='snappy'` for cost governance (constitution IV)
