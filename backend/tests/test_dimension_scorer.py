"""Tests for the dimension scoring engine + scoring API (task 7.2).

Covers Requirement 12.4:

- ``state_for_score`` maps numeric scores to states at the documented
  boundaries (>=75 green, 50-74 yellow, <50 red, no data -> gray).
- ``compute_dimension_scores`` produces in-bounds scores, reports all-``gray``
  when telemetry is missing, and reflects telemetry signals (e.g. monitoring
  disabled -> red).
- ``GET /api/scoring/issues`` returns a valid success envelope, with each
  issue carrying a ``dimension_scores`` object for its workload.

An isolated temp SQLite DB is configured via CLOVER_DB_PATH before the app is
imported so tests never touch the real clover.db.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_scoring_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.modules.scoring import dimension_scorer  # noqa: E402
from backend.modules.scoring.dimension_scorer import (  # noqa: E402
    compute_dimension_scores,
    state_for_score,
)
from backend.schemas.telemetry import TelemetrySnapshot  # noqa: E402


def _healthy_snapshot(workload_id: str) -> TelemetrySnapshot:
    """A plainly-healthy telemetry payload (all dimensions should be strong)."""
    return TelemetrySnapshot(
        workload_id=workload_id,
        cpu_usage_percent=45.0,
        memory_usage_percent=55.0,
        storage_gb=100.0,
        runtime_hours_24h=8.0,
        request_count_24h=50000,
        error_rate_percent=0.4,
        latency_ms=120.0,
        public_exposure=False,
        public_storage=False,
        vulnerability_severity="none",
        critical_vulnerability_count=0,
        access_anomaly_detected=False,
        monitoring_enabled=True,
        cost_per_hour=0.5,
        cost_24h=12.0,
        cost_30d_forecast=360.0,
        energy_kwh_24h=14.0,
        carbon_kgco2e_24h=5.6,
        carbon_intensity_gco2_per_kwh=400.0,
        timestamp=datetime.now(timezone.utc),
    )


# --------------------------------------------------------------------------- #
# State mapping boundaries (Requirement 12.4 / Property 12)
# --------------------------------------------------------------------------- #
def test_state_mapping_boundaries():
    # >= 75 -> green (inclusive boundary).
    assert state_for_score(75.0) == "green"
    assert state_for_score(100.0) == "green"
    # 50 <= score < 75 -> yellow.
    assert state_for_score(74.0) == "yellow"
    assert state_for_score(50.0) == "yellow"
    # < 50 -> red.
    assert state_for_score(49.0) == "red"
    assert state_for_score(0.0) == "red"
    # No data -> gray.
    assert state_for_score(None) == "gray"


# --------------------------------------------------------------------------- #
# compute_dimension_scores
# --------------------------------------------------------------------------- #
def test_no_telemetry_is_all_gray():
    scores = compute_dimension_scores("wl-x", telemetry=None)
    assert scores.workload_id == "wl-x"
    for dim in dimension_scorer.DIMENSIONS:
        ds = getattr(scores, dim)
        assert ds.state == "gray"


def test_healthy_telemetry_scores_in_bounds_and_strong():
    scores = compute_dimension_scores("wl-x", _healthy_snapshot("wl-x"))
    for dim in dimension_scorer.DIMENSIONS:
        ds = getattr(scores, dim)
        assert 0.0 <= ds.score <= 100.0
        assert ds.state in {"green", "yellow", "red", "gray"}
    # A healthy workload with monitoring on should be green on security & monitoring.
    assert scores.monitoring.state == "green"
    assert scores.security.state == "green"


def test_monitoring_disabled_is_red():
    snap = _healthy_snapshot("wl-x")
    snap = snap.model_copy(update={"monitoring_enabled": False})
    scores = compute_dimension_scores("wl-x", snap)
    assert scores.monitoring.score == 0.0
    assert scores.monitoring.state == "red"


def test_security_deductions_lower_security_score():
    snap = _healthy_snapshot("wl-x").model_copy(
        update={
            "vulnerability_severity": "critical",
            "critical_vulnerability_count": 3,
            "public_exposure": True,
            "public_storage": True,
            "access_anomaly_detected": True,
        }
    )
    scores = compute_dimension_scores("wl-x", snap)
    # 25 (critical) + 30 (3 vulns capped path) + 20 + 15 + 20 -> well below 50.
    assert scores.security.score < 50.0
    assert scores.security.state == "red"


def test_open_issue_depresses_matching_dimension():
    snap = _healthy_snapshot("wl-x")
    baseline = compute_dimension_scores("wl-x", snap)
    issues = [{"issue_category": "performance", "severity": "critical", "status": "new"}]
    scored = compute_dimension_scores("wl-x", snap, issues)
    assert scored.performance.score < baseline.performance.score


# --------------------------------------------------------------------------- #
# GET /api/scoring/issues envelope
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_scoring_issues_endpoint_returns_valid_envelope(client):
    # Empty (no issues) still returns a well-formed success envelope.
    resp = client.get("/api/scoring/issues")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert "data" in body
    assert "issues" in body["data"]
    assert body["data"]["count"] == len(body["data"]["issues"])


def test_scoring_issues_includes_dimension_scores(client):
    # Create an issue via the mock pipeline, then verify it is scored.
    client.post("/api/mock/reset")
    client.post("/api/mock/trigger/trigger_cost_spike")
    run = client.post("/api/detection/run/wl-costly-vm-001")
    assert run.status_code == 200, run.text

    resp = client.get("/api/scoring/issues", params={"workload_id": "wl-costly-vm-001"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["count"] >= 1
    first = data["issues"][0]
    assert first["workload_id"] == "wl-costly-vm-001"
    # Dimension scores attached and well-formed.
    dims = first["dimension_scores"]
    for dim in dimension_scorer.DIMENSIONS:
        assert dim in dims
        assert 0.0 <= dims[dim]["score"] <= 100.0
        assert dims[dim]["state"] in {"green", "yellow", "red", "gray"}


def teardown_module(module):  # noqa: D401 - pytest hook
    """Remove the temp DB directory created for this module."""
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
