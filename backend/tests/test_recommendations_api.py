"""Tests for the NBA pipeline + Recommendations/Forecast API (task 4.4).

Covers Requirements 5.1 and 21.1 end to end:

- Triggering a mock scenario flows telemetry -> detection -> ISSUE_DETECTED ->
  the subscribed NBA pipeline, producing a persisted Recommendation with the
  correct triggered rule, a forecast_model_result, and an
  optimization_impact_forecast whose savings are non-negative and arithmetically
  consistent (without - after == savings per dimension).
- ``POST /api/recommendations/generate/{issueId}`` generates a recommendation on
  demand (and 404s for an unknown issue).
- ``GET /api/recommendations/{id}`` returns detail (and 404s for unknown).
- ``POST /api/forecast/{workloadId}`` returns a 30-day forecast (and 404s for an
  unknown workload).

An isolated temp SQLite DB is configured via CLOVER_DB_PATH before the app is
imported so tests never touch the real clover.db.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_recommendations_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services import recommendation_service  # noqa: E402


@pytest.fixture(scope="module")
def client():
    """TestClient with lifespan active (seeds workloads + baseline + subscribes)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_between_tests(client):
    """Reset to a clean healthy baseline before each test for isolation."""
    client.post("/api/mock/reset")
    yield


def _assert_forecast_present(recommendation: dict) -> None:
    """Assert the recommendation carries a non-empty forecast_model_result."""
    fmr = recommendation["forecast_model_result"]
    assert fmr is not None
    assert fmr["model_name"]
    assert fmr["predicted_cost_30d"] >= 0.0
    assert fmr["predicted_energy_kwh_30d"] >= 0.0
    assert fmr["predicted_carbon_kgco2e_30d"] >= 0.0


def _assert_savings_consistent(recommendation: dict) -> None:
    """Assert optimization impact savings are non-negative and consistent."""
    oif = recommendation["optimization_impact_forecast"]
    assert oif is not None
    without = oif["forecast_without_action"]
    after = oif["forecast_after_action"]
    savings = oif["projected_savings"]
    for dim in ("cost_30d", "energy_30d_kwh", "carbon_30d_kgco2e"):
        assert savings[dim] >= 0.0, f"savings for {dim} must be non-negative"
        assert without[dim] - after[dim] == pytest.approx(savings[dim]), (
            f"without - after must equal savings for {dim}"
        )


def _wait_for_recommendation(client, workload_id: str, *, attempts: int = 30):
    """Poll for a recommendation for a workload, pumping the event loop.

    The detection -> ISSUE_DETECTED -> NBA chain runs as background tasks; a
    benign request between checks lets the event loop drain them.
    """
    for _ in range(attempts):
        recs = recommendation_service.list_recommendations(workload_id=workload_id)
        if recs:
            return recs[0]
        client.get("/api/mock/status")
    return None


# --------------------------------------------------------------------------- #
# Event-driven pipeline: ISSUE_DETECTED -> Recommendation (Requirement 5.1)
# --------------------------------------------------------------------------- #
def test_issue_detected_event_produces_recommendation(client):
    # Missing-monitoring scenario targets the (non-prod) CI pipeline workload.
    trig = client.post("/api/mock/trigger/trigger_missing_monitoring")
    assert trig.status_code == 200, trig.text
    workload_id = trig.json()["data"]["workload_id"]
    assert workload_id == "wl-ci-pipeline-001"

    recommendation = _wait_for_recommendation(client, workload_id)
    assert recommendation is not None, "NBA subscription should produce a recommendation"

    # Correct rule traceability for a missing-monitoring issue.
    assert recommendation["rule_triggered"]["rule_id"] == "RULE-MON-001"
    assert recommendation["rule_triggered"]["conditions_matched"]
    assert recommendation["recommendation_type"] == "enable_monitoring"

    _assert_forecast_present(recommendation)
    _assert_savings_consistent(recommendation)
    # Monitoring is a non-savings action (factor 1.0) -> zero projected savings.
    assert recommendation["optimization_impact_forecast"]["projected_savings"][
        "cost_30d"
    ] == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Generate-on-demand endpoint (Requirements 5.1, 21.1)
# --------------------------------------------------------------------------- #
def test_generate_recommendation_endpoint_for_cost_spike(client):
    client.post("/api/mock/trigger/trigger_cost_spike")
    issue = client.post("/api/detection/run/wl-costly-vm-001").json()["data"]["issue"]
    issue_id = issue["issue_id"]

    resp = client.post(f"/api/recommendations/generate/{issue_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    rec = body["data"]

    assert rec["issue_id"] == issue_id
    assert rec["workload_id"] == "wl-costly-vm-001"
    # Cost spike -> RULE-COST-001 -> resize_workload (savings-bearing action).
    assert rec["rule_triggered"]["rule_id"] == "RULE-COST-001"
    assert rec["recommendation_type"] == "resize_workload"
    assert rec["risk_level"] in {"low", "medium", "high", "critical"}
    assert rec["required_execution_mode"] in {
        "auto_fix",
        "user_approval_required",
        "human_escalation_required",
    }

    _assert_forecast_present(rec)
    _assert_savings_consistent(rec)
    # A resize action retains < 100% of cost, so savings should be positive.
    assert rec["optimization_impact_forecast"]["projected_savings"]["cost_30d"] > 0.0

    # The recommendation is retrievable by id.
    got = client.get(f"/api/recommendations/{rec['recommendation_id']}")
    assert got.status_code == 200, got.text
    assert got.json()["data"]["recommendation_id"] == rec["recommendation_id"]


def test_generate_recommendation_unknown_issue_404(client):
    resp = client.post("/api/recommendations/generate/iss-does-not-exist")
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------- #
# Recommendation detail (Requirement 21.1)
# --------------------------------------------------------------------------- #
def test_get_recommendation_unknown_404(client):
    resp = client.get("/api/recommendations/rec-does-not-exist")
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------- #
# Forecast endpoint (Requirements 6.1, 21.1)
# --------------------------------------------------------------------------- #
def test_forecast_endpoint_returns_forecast(client):
    # Baseline seeding gives every workload telemetry; trigger ensures freshness.
    client.post("/api/mock/trigger/trigger_cost_spike")
    resp = client.post("/api/forecast/wl-costly-vm-001")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["workload_id"] == "wl-costly-vm-001"
    forecast = data["forecast"]
    assert forecast["model_name"]
    assert forecast["predicted_cost_30d"] >= 0.0
    assert forecast["predicted_energy_kwh_30d"] >= 0.0
    assert forecast["predicted_carbon_kgco2e_30d"] >= 0.0


def test_forecast_unknown_workload_404(client):
    resp = client.post("/api/forecast/wl-not-real")
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"


def teardown_module(module):  # noqa: D401 - pytest hook
    """Remove the temp DB directory created for this module."""
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
