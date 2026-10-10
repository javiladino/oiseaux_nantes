import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../ingestion"))

from inaturalist_client import fetch_observations


@pytest.mark.integration
def test_fetch_observations_returns_valid_structure():
    """Live read-only iNaturalist API call — no writes, no side effects."""
    results = fetch_observations(watermark=None)
    assert isinstance(results, list)
    if results:
        obs = results[0]
        assert "id" in obs
        assert "created_at" in obs
        assert "location" in obs
        assert "taxon" in obs
        assert "user" in obs
        assert obs.get("quality_grade") in ("research", "needs_id", "casual")
