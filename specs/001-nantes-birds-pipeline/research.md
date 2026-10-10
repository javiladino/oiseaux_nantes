# Research: Nantes Birds Pipeline

**Feature**: `001-nantes-birds-pipeline` | **Date**: 2026-10-10

All NEEDS CLARIFICATION items from the Technical Context have been resolved below.

---

## 1. iNaturalist API v1 — Incremental Ingestion

### Decision
Use `created_d1` + `created_d2` (ISO 8601 date strings, `YYYY-MM-DD`) to filter observations
by creation date. Store the watermark as a UTC timestamp in SSM; on each run derive
`created_d1 = last_successful_run_date` and `created_d2 = today`.

### Findings

**Endpoint**: `GET https://api.inaturalist.org/v1/observations`

**Bounding box parameters** (confirmed):
```
swlat=46.8600781&swlng=-2.6257395&nelat=47.8359431&nelng=-0.9466615
```

**Incremental filter parameters**:
- `created_d1` — lower bound date (inclusive), format `YYYY-MM-DD`
- `created_d2` — upper bound date (inclusive), format `YYYY-MM-DD`
- `updated_since` — ISO 8601 datetime for records updated after a timestamp (alternative for
  update-based incremental; not used in v1 since spec targets creation date)

**Taxon**: Aves = `taxon_id=3` (class Aves, iNaturalist taxon ID confirmed)

**Pagination**:
- `page` (1-indexed) + `per_page` (max 200)
- Response includes `total_results` integer → derive `ceil(total_results / per_page)` pages
- Rate limit: 100 req/min documented; ~1 req/s is a safe conservative default per constitution

**Response object key fields**:
```json
{
  "id": 123456,
  "created_at": "2024-05-01T10:23:00+00:00",
  "observed_on": "2024-04-30",
  "observed_time_zone": "Europe/Paris",
  "quality_grade": "research",
  "location": "47.2184,-1.5536",        // "lat,lng" string — must be split
  "positional_accuracy": 10,
  "taxon": {
    "id": 18793,
    "name": "Larus michahellis",
    "preferred_common_name": "Yellow-legged Gull",
    "rank": "species",
    "threatened": false
  },
  "user": {
    "id": 9876,
    "login": "birder42",
    "name": "Jane Birder"
  }
}
```

**`quality_grade` valid values**: `research`, `needs_id`, `casual` (confirmed — matches FR-010)

**Pagination hard limit**: The API enforces a **10,000 total-results ceiling** per query window
(`page * per_page ≤ 10,000`; pagination breaks past page 333). For Nantes daily volumes this
ceiling is never hit, but the design must use the `id_above` cursor strategy as a safeguard:

```
Strategy: id_above cursor
  1. First call: page=1, per_page=200, order_by=id, order=asc
  2. Save max(id) from batch → last_id
  3. Subsequent calls: id_above=last_id, per_page=200 (no page param)
  4. Stop when len(results) < per_page (last page)
```

This avoids the 10k ceiling and prevents duplicate observations from mid-run page shifts.

**Gotchas**:
- `location` is a `"lat,lng"` string, not an object; splitting required in staging
- `preferred_common_name` may be absent (null) for uncommon taxa — acceptable per spec
- Pagination overlap possible if observations are created mid-run; dedup on `id` in staging
  handles this (FR-014); `id_above` cursor further mitigates this
- `created_at` is timezone-aware; cast to UTC in staging
- `created_d1`/`created_d2` also accept `YYYY-MM-DDTHH:MM:SS` for sub-day precision — use
  full datetime format for the watermark to avoid re-ingesting partial days

### Alternatives considered
- Using `updated_since` for update-inclusive incremental: deferred to v2; complicates dedup
  logic and the spec only requires capturing newly created observations (FR-002)
- Page-based pagination only: rejected due to 10k ceiling; `id_above` cursor is more robust
- GraphQL / export API: requires authentication, overkill for this volume

---

## 2. Lambda Watermark Pattern (SSM Parameter Store)

### Decision
Store a single SSM `String` parameter (`/birds-pipeline/last_successful_run_date`) holding the
last successful ingestion date as `YYYY-MM-DD`. Read before run, write atomically after all S3
writes succeed. Lambda IAM role scoped to that single parameter ARN.

### Rationale
- SSM `String` parameters are free-tier (standard tier), durable, and support atomic put
- Keeps state outside Lambda (stateless function) without adding DynamoDB cost/complexity
- Single-parameter scope satisfies least-privilege constraint (constitution IV + FR-002)

### Pattern

```python
# ssm_watermark.py
def get_watermark(ssm_client, param_name: str) -> str | None:
    try:
        resp = ssm_client.get_parameter(Name=param_name)
        return resp["Parameter"]["Value"]   # "YYYY-MM-DD" or None on first run
    except ssm_client.exceptions.ParameterNotFound:
        return None

def put_watermark(ssm_client, param_name: str, value: str) -> None:
    ssm_client.put_parameter(Name=param_name, Value=value,
                              Type="String", Overwrite=True)
```

---

## 3. dbt-athena Community Adapter

### Decision
Use `dbt-athena-community` (not the deprecated `dbt-athena` AWS package). Configure models
with `file_format = 'parquet'`, `write_compression = 'snappy'`, and
`incremental_strategy = 'insert_overwrite'` partitioned by `year`/`month` for `fct_observations`.

### Findings

**Package**: `dbt-athena` (PyPI; `dbt-athena-community` is now a backwards-compat wrapper —
install `dbt-athena` directly for new projects; supports dbt-core 1.5+)

**`profiles.yml` required fields**:
```yaml
birds_pipeline:
  target: dev
  outputs:
    dev:
      type: athena
      region_name: eu-west-3          # Paris region (closest to Nantes)
      s3_staging_dir: s3://my-bucket/athena-results/
      s3_data_dir: s3://my-bucket/processed/
      database: awsdatacatalog         # Glue catalog
      schema: birds_dbt               # Glue database name
      threads: 4
```

**Model-level Parquet + Snappy config** (add to each model's `config` block or `dbt_project.yml`):
```sql
{{ config(
    materialized = 'incremental',
    incremental_strategy = 'insert_overwrite',
    partitioned_by = ['year', 'month'],
    format = 'parquet',
    write_compression = 'snappy'
) }}
```

Note: the key is `format` (not `file_format`) in dbt-athena.

**Incremental strategy**: `insert_overwrite` is the recommended strategy for Athena; it
overwrites Hive partitions atomically. `merge` requires Iceberg tables (out of scope v1).
For append-only fact tables, `insert_overwrite` on `(year, month)` partitions is safe and
idempotent.

**External table (raw JSON source)**:
The raw S3 JSON is exposed as an Athena external table via AWS Glue crawler (infrastructure
concern) or a manual DDL. In dbt, reference it as a `source` in `sources.yml`:
```yaml
sources:
  - name: raw_inaturalist
    database: awsdatacatalog
    schema: birds_raw            # Glue database for raw zone
    tables:
      - name: observations
        description: "Raw JSON observations partitioned by year/month"
        external: true
```
dbt-athena reads external tables normally; it does not manage their DDL.

**Glue Catalog**: dbt-athena creates and updates Glue tables automatically when running
`dbt run`. No manual DDL needed for managed (non-external) models.

**External table (raw JSON source)**: Use `dbt-external-tables` package:
```yaml
# sources.yml
sources:
  - name: raw_inaturalist
    schema: birds_raw
    tables:
      - name: observations
        external:
          location: s3://my-bucket/raw/inaturalist/observations/
          row_format: >
            SERDE 'org.openx.data.jsonserde.JsonSerDe'
          partitions:
            - name: year
              data_type: string
            - name: month
              data_type: string
```
Register with: `dbt run-operation stage_external_sources`

**Gotchas**:
- `s3_staging_dir` holds Athena query results (temporary); `s3_data_dir` holds dbt model data
- Column names with dots must be renamed in staging (Athena/Parquet limitation)
- `insert_overwrite` re-writes entire partitions — ensure `fct_observations` is partitioned
  before incremental runs; first run must `--full-refresh`
- Athena does not support `DELETE` or `UPDATE` natively; merge requires Iceberg (deferred)
- 100-partition limit on Hive tables; year+month gives ~12–24 partitions — well within limit
- Raw JSON parsing requires `org.openx.data.jsonserde.JsonSerDe` for complex nested fields

### Alternatives considered
- AWS-native `dbt-athena` package: deprecated in favor of community adapter; rejected
- Iceberg tables with `merge` strategy: supports true upserts but adds operational complexity
  and cost; deferred to v2 if update-based incremental is needed

---

## 4. Power BI + Athena Import Mode

### Decision
Connect Power BI to Athena via the **AWS Athena ODBC driver** (Simba/Amazon). Use **Import**
mode with a daily scheduled refresh. No DirectQuery (excluded per spec assumption).

### Rationale
- Import mode caches data in Power BI's in-memory engine → sub-second visuals without per-query
  Athena cost
- Daily refresh aligned with ingestion cadence (SC-001: data available within 24h)
- DirectQuery would incur Athena scan cost on every visual interaction (rejected by spec)

### Connection setup (quickstart detail)
1. Install Amazon Athena ODBC driver (64-bit)
2. Power BI Desktop → Get Data → ODBC → DSN pointing to Athena `birds_dbt` schema
3. Select `fct_observations`, `dim_species`, `dim_users`, `dim_date`
4. Set relationships in Model view (star schema)
5. Publish to Power BI Service → configure scheduled refresh (daily, post-ingestion)

---

## Summary Table

| Question | Answer |
|----------|--------|
| Incremental filter params | `created_d1` / `created_d2` (YYYY-MM-DD) |
| Taxon ID for Aves | `3` |
| Max `per_page` | `200` |
| Rate limit (safe) | ~1 req/s (100 req/min documented) |
| `location` format | `"lat,lng"` string — split in staging |
| `quality_grade` values | `research`, `needs_id`, `casual` |
| dbt adapter package | `dbt-athena-community` |
| dbt incremental strategy | `insert_overwrite` partitioned by `(year, month)` |
| Parquet compression | Snappy (`write_compression = 'snappy'`) |
| Power BI connection | Athena ODBC (Simba), Import mode, daily refresh |
