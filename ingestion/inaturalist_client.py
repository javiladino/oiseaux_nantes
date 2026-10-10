import time
import requests

API_BASE = "https://api.inaturalist.org/v1/observations"
HEADERS = {"User-Agent": "oiseaux-nantes-pipeline/1.0"}
BBOX = {
    "swlat": 46.8600781,
    "swlng": -2.6257395,
    "nelat": 47.8359431,
    "nelng": -0.9466615,
}
TAXON_ID = 3
PER_PAGE = 200
MAX_RETRIES = 3


def fetch_observations(watermark: str | None) -> list[dict]:
    """Paginate iNaturalist API using id_above cursor and return all observation dicts."""
    params = {
        "taxon_id": TAXON_ID,
        "swlat": BBOX["swlat"],
        "swlng": BBOX["swlng"],
        "nelat": BBOX["nelat"],
        "nelng": BBOX["nelng"],
        "per_page": PER_PAGE,
        "order_by": "id",
        "order": "asc",
    }
    if watermark:
        params["created_d1"] = watermark

    all_results: list[dict] = []
    last_id: int | None = None

    while True:
        if last_id is not None:
            params["id_above"] = last_id
            params.pop("page", None)
        else:
            params.setdefault("page", 1)

        batch = _get_with_retry(params)
        results = batch.get("results", [])
        all_results.extend(results)

        if len(results) < PER_PAGE:
            break

        last_id = max(r["id"] for r in results)
        time.sleep(1)

    return all_results


def _get_with_retry(params: dict) -> dict:
    delay = 1
    for attempt in range(MAX_RETRIES):
        resp = requests.get(API_BASE, params=params, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 503):
            if attempt < MAX_RETRIES - 1:
                time.sleep(delay)
                delay *= 2
                continue
        resp.raise_for_status()
    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded for iNaturalist API")
