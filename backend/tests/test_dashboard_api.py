"""Tests for the Dashboard API (task 8.1).

Covers Requirements 16.1, 16.2 and 21.1 (spec 10 §6): the dashboard aggregate
endpoints return valid success envelopes, the summary stat cards are integer
counts with a structured projected-savings rollup, and both heatmap endpoints
return exactly one entry per seeded workload (composite Priority_Score grid +
matrix DimensionScores view).

An isolated temp SQLite DB is configured via CLOVER_DB_PATH before the app is
imported so tests never touch the real clover.db. The app lifespan seeds the
workload set + healthy baseline telemetry, which is what the heatmaps score.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_dashboard_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services import workload_service  # noqa: E402


@pytest.fixture(scope="module")
def client():
    """TestClient with lifespan active (seeds workloads + baseline telemetry)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_between_tests(client):
    client.post("/api/mock/reset")
    yield


def _data(resp) -> dict:
    """Assert a 200 + success envelope and return the ``data`` payload."""
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert "data" in body and body["data"] is not None
    return body["data"]


def _workload_count() -> int:
    return len(workload_service.list_workloads())


def test_summary_returns_integer_counts_and_savings(client):
    data = _data(client.get("/api/dashboard/summary"))

    # Stat-card counts are non-negative integers.
    for key in (
        "total_workloads",
        "active_issues",
        "critical_issues",
        "pending_approvals",
        "open_recommendations",
    ):
        assert isinstance(data[key], int), f"{key} should be an int"
        assert data[key] >= 0

    # total_workloads matches what was seeded.
    assert data["total_workloads"] == _workload_count()
    assert data["total_workloads"] > 0

    # Projected savings is a structured cost/energy/carbon rollup.
    savings = data["projected_savings"]
    for key in ("cost_30d", "energy_30d_kwh", "carbon_30d_kgco2e"):
        assert isinstance(savings[key], (int, float))
        assert savings[key] >= 0.0


def test_composite_heatmap_one_cell_per_workload(client):
    data = _data(client.get("/api/dashboard/heatmap/composite"))

    assert data["count"] == _workload_count()
    assert len(data["cells"]) == data["count"]

    seen_ids = set()
    for cell in data["cells"]:
        assert cell["workload_id"]
        seen_ids.add(cell["workload_id"])
        # Priority score is a 0-100 number.
        assert isinstance(cell["priority_score"], (int, float))
        assert 0.0 <= cell["priority_score"] <= 100.0
        # Full score detail is attached for the tooltip.
        assert cell["score_detail"]["workload_id"] == cell["workload_id"]

    # One cell per distinct workload.
    assert len(seen_ids) == _workload_count()


def test_matrix_heatmap_one_row_per_workload_with_six_dimensions(client):
    data = _data(client.get("/api/dashboard/heatmap/matrix"))

    assert data["count"] == _workload_count()
    assert len(data["rows"]) == data["count"]

    dimensions = ("security", "energy", "carbon", "cost", "performance", "monitoring")
    valid_states = {"green", "yellow", "red", "gray"}
    for row in data["rows"]:
        scores = row["dimension_scores"]
        assert scores["workload_id"] == row["workload_id"]
        for dimension in dimensions:
            cell = scores[dimension]
            assert 0.0 <= cell["score"] <= 100.0
            assert cell["state"] in valid_states


def test_savings_rollup_envelope(client):
    data = _data(client.get("/api/dashboard/savings"))

    assert isinstance(data["recommendation_count"], int)
    assert data["recommendation_count"] >= 0
    savings = data["projected_savings"]
    for key in ("cost_30d", "energy_30d_kwh", "carbon_30d_kgco2e"):
        assert isinstance(savings[key], (int, float))
        assert savings[key] >= 0.0


def test_recent_actions_envelope_and_limit(client):
    data = _data(client.get("/api/dashboard/recent-actions"))
    assert isinstance(data["actions"], list)
    assert data["count"] == len(data["actions"])

    # The limit query parameter is honoured.
    data_limited = _data(client.get("/api/dashboard/recent-actions?limit=3"))
    assert len(data_limited["actions"]) <= 3


def test_recent_actions_reflects_a_triggered_remediation(client):
    """After an auto-fix flows end to end, it appears in recent actions + savings."""
    from backend.services import recommendation_service

    trig = client.post("/api/mock/trigger/trigger_missing_monitoring")
    assert trig.status_code == 200, trig.text
    workload_id = trig.json()["data"]["workload_id"]

    # Wait for the ISSUE_DETECTED -> NBA chain to produce a recommendation.
    recommendation = None
    for _ in range(30):
        recs = recommendation_service.list_recommendations(workload_id=workload_id)
        if recs:
            recommendation = recs[0]
            break
        client.get("/api/mock/status")
    assert recommendation is not None, "expected a recommendation to be generated"

    # Execute the auto-fix remediation.
    rec_id = recommendation["recommendation_id"]
    ex = client.post(f"/api/remediation/execute/{rec_id}")
    assert ex.status_code == 200, ex.text
    rem_id = ex.json()["data"]["remediation_id"]

    data = _data(client.get("/api/dashboard/recent-actions"))
    assert any(a["remediation_id"] == rem_id for a in data["actions"])


def teardown_module(module):  # noqa: D401 - pytest hook
    """Remove the temp DB directory created for this module."""
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
