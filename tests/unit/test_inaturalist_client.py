import time
import pytest
import responses as resp_lib

from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../ingestion"))

import inaturalist_client as client


def _make_page(ids, total=None):
    results = [{"id": i, "created_at": "2024-05-01T10:00:00+00:00"} for i in ids]
    return {"total_results": total or len(ids), "results": results}


@patch("inaturalist_client.time.sleep")
@patch("inaturalist_client.requests.get")
def test_first_run_no_watermark_fetches_all(mock_get, mock_sleep):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: _make_page([1, 2, 3]))
    results = client.fetch_observations(None)
    assert len(results) == 3
    called_params = mock_get.call_args[1]["params"]
    assert "created_d1" not in called_params


@patch("inaturalist_client.time.sleep")
@patch("inaturalist_client.requests.get")
def test_incremental_run_passes_created_d1(mock_get, mock_sleep):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: _make_page([10, 11]))
    client.fetch_observations("2024-05-01T00:00:00")
    called_params = mock_get.call_args[1]["params"]
    assert called_params["created_d1"] == "2024-05-01T00:00:00"


@patch("inaturalist_client.time.sleep")
@patch("inaturalist_client.requests.get")
def test_id_above_cursor_advances(mock_get, mock_sleep):
    page1 = _make_page(list(range(1, 201)))   # 200 results → triggers next page
    page2 = _make_page(list(range(201, 210)))  # 9 results → last page
    mock_get.side_effect = [
        MagicMock(status_code=200, json=lambda p=page1: p),
        MagicMock(status_code=200, json=lambda p=page2: p),
    ]
    results = client.fetch_observations(None)
    assert len(results) == 209
    second_call_params = mock_get.call_args_list[1][1]["params"]
    assert second_call_params["id_above"] == 200


@patch("inaturalist_client.time.sleep")
@patch("inaturalist_client.requests.get")
def test_zero_results_returns_empty(mock_get, mock_sleep):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: {"results": [], "total_results": 0})
    results = client.fetch_observations(None)
    assert results == []


@patch("inaturalist_client.time.sleep")
@patch("inaturalist_client.requests.get")
def test_429_triggers_exponential_backoff_and_retries(mock_get, mock_sleep):
    ok_resp = MagicMock(status_code=200, json=lambda: _make_page([1]))
    retry_resp = MagicMock(status_code=429)
    mock_get.side_effect = [retry_resp, ok_resp]
    results = client.fetch_observations(None)
    assert len(results) == 1
    assert mock_sleep.call_count >= 1


@patch("inaturalist_client.time.sleep")
@patch("inaturalist_client.requests.get")
def test_max_retries_exceeded_raises(mock_get, mock_sleep):
    mock_get.return_value = MagicMock(status_code=429)
    with pytest.raises(RuntimeError, match="Max retries"):
        client.fetch_observations(None)
