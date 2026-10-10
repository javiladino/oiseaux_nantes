# Contract: iNaturalist API v1 — Observations Endpoint

**Consumer**: `ingestion/inaturalist_client.py` (Lambda)
**Provider**: iNaturalist public API v1 (no authentication required)
**Date**: 2026-10-10

---

## Endpoint

```
GET https://api.inaturalist.org/v1/observations
```

## Required Headers

```
User-Agent: oiseaux-nantes-pipeline/1.0 (contact: <pipeline-owner-email>)
Accept: application/json
```

The `User-Agent` header is **mandatory** per constitution principle II (Ethical API Ingestion).

## Query Parameters (Incremental Run)

| Parameter | Type | Required | Example | Notes |
|-----------|------|----------|---------|-------|
| `taxon_id` | integer | Yes | `3` | Class Aves |
| `swlat` | float | Yes | `46.8600781` | Greater Nantes bounding box |
| `swlng` | float | Yes | `-2.6257395` | |
| `nelat` | float | Yes | `47.8359431` | |
| `nelng` | float | Yes | `-0.9466615` | |
| `created_d1` | string | Yes (incremental) | `2024-05-01T00:00:00` | ISO 8601; lower bound on `created_at` |
| `created_d2` | string | Yes (incremental) | `2024-05-01T23:59:59` | ISO 8601; upper bound on `created_at` |
| `per_page` | integer | Yes | `200` | Maximum value: 200 |
| `order_by` | string | Yes | `id` | Required for `id_above` cursor strategy |
| `order` | string | Yes | `asc` | Ascending order on `id` |
| `id_above` | integer | No (first page) | `123456` | Cursor for pages after first |

**Note on `created_d1` on first run**: When no watermark exists, omit `created_d1`/`created_d2`
to retrieve all historical observations.

## Pagination Strategy

Use `id_above` cursor (not page-based) to avoid the 10,000-result ceiling:

```
1. Call with per_page=200, order_by=id, order=asc (no id_above)
2. Extract results[]; record max(id) as last_id
3. If len(results) < per_page → last page; stop
4. Else → call again with id_above=last_id; go to step 2
```

**Rate limit**: 1 request per second (sleep 1s between calls).

## Response Schema

```json
{
  "total_results": 1250,
  "page": 1,
  "per_page": 200,
  "results": [
    {
      "id": 123456,
      "created_at": "2024-05-01T10:23:00+00:00",
      "observed_on": "2024-04-30",
      "observed_time_zone": "Europe/Paris",
      "quality_grade": "research",
      "location": "47.2184,-1.5536",
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
  ]
}
```

## Field Contracts

| Field path | Type | Nullable | Constraint |
|------------|------|----------|------------|
| `results[].id` | integer | No | Unique per observation; use as dedup key |
| `results[].created_at` | string | No | ISO 8601 with timezone offset |
| `results[].observed_on` | string | No | `YYYY-MM-DD` format |
| `results[].quality_grade` | string | No | One of: `research`, `needs_id`, `casual` |
| `results[].location` | string | Yes | `"lat,lng"` format; null if coords obscured |
| `results[].positional_accuracy` | integer | Yes | Meters |
| `results[].taxon.id` | integer | No | iNaturalist taxon ID |
| `results[].taxon.name` | string | No | Scientific name |
| `results[].taxon.preferred_common_name` | string | Yes | Absent for uncommon taxa |
| `results[].taxon.rank` | string | No | Taxonomic rank |
| `results[].taxon.threatened` | boolean | No | iNaturalist flag |
| `results[].user.id` | integer | No | iNaturalist user ID |
| `results[].user.login` | string | No | Username |
| `results[].user.name` | string | Yes | Display name |

## Error Handling Contract

| HTTP Status | Meaning | Lambda behavior |
|-------------|---------|-----------------|
| 200 | Success | Parse and write to S3 |
| 429 | Rate limited | Exponential backoff + retry (max 3 attempts) |
| 500/503 | API error | Retry with backoff; fail Lambda after max retries |
| Timeout | Network issue | Retry with backoff; fail Lambda after max retries |

On Lambda failure: watermark is **NOT** updated; EventBridge retries on next schedule;
CloudWatch alarm fires on Lambda error metric.

## Storage Contract (Output)

Each S3 file written by Lambda:
- **Path**: `s3://{bucket}/raw/inaturalist/observations/year={YYYY}/month={MM}/{timestamp}.json`
- **Format**: NDJSON — one JSON object per line (each `results[]` item is one line)
- **Content**: Raw API response objects, exactly as received (no transformation)
- **Encoding**: UTF-8
