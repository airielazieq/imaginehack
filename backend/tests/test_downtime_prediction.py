"""Tests for the Downtime Prediction engine (task 7.3, Requirement 14).

Covers the predictor's trend analysis, the 12-point risk timeline, and the
``GET /api/workloads/{id}/prediction`` endpoint. Mirrors design Property 14
(Downtime Prediction Output Completeness) with concrete examples:

- probability in [0, 100]
- non-empty primary_signal
- confidence in {low, medium, high}
- risk_timeline has exactly 12 numeric points
- recommended_preemptive_action present iff probability > 70%

An isolated temp SQLite DB is configured via CLOVER_DB_PATH before the app is
imported so the endpoint tests never touch the real clover.db.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_prediction_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.modules.downtime_prediction import predictor, timeline  # noqa: E402
from backend.schemas.telemetry import TelemetrySnapshot  # noqa: E402
from backend.schemas.workload import Workload  # noqa: E402
from backend.services import telemetry_service, workload_service  # noqa: E402

_CONFIDENCE_LEVELS = {"low", "medium", "high"}
_BASE_TS = datetime(2026, 6, 20, 0, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Fixtures / builders
# --------------------------------------------------------------------------- #
def _snapshot_dict(
    *,
    workload_id: str = "wl-test-001",
    index: int = 0,
    cpu: float = 20.0,
    memory: float = 30.0,
    error_rate: float = 0.5,
    latency: float = 100.0,
) -> dict:
    """Build a full TelemetrySnapshot dict (chronological ``index`` -> timestamp)."""
    snap = TelemetrySnapshot(
        workload_id=workload_id,
        cpu_usage_percent=cpu,
        memory_usage_percent=memory,
        storage_gb=10.0,
        runtime_hours_24h=24.0,
        request_count_24h=1000,
        error_rate_percent=error_rate,
        latency_ms=latency,
        public_exposure=False,
        public_storage=False,
        vulnerability_severity="none",
        critical_vulnerability_count=0,
        access_anomaly_detected=False,
        monitoring_enabled=True,
        cost_per_hour=1.0,
        cost_24h=24.0,
        cost_30d_forecast=720.0,
        energy_kwh_24h=5.0,
        carbon_kgco2e_24h=2.0,
        carbon_intensity_gco2_per_kwh=400.0,
        timestamp=_BASE_TS + timedelta(hours=index),
    )
    return snap.model_dump(mode="json")


def _degrading_history(n: int = 12, workload_id: str = "wl-test-001") -> list[dict]:
    """Memory rising 70 -> ~96% over ``n`` hourly points (most recent first)."""
    chrono = [
        _snapshot_dict(
            workload_id=workload_id,
            index=i,
            memory=70.0 + (26.0 * i / (n - 1)),
            error_rate=0.5 + (2.0 * i / (n - 1)),
        )
        for i in range(n)
    ]
    return list(reversed(chrono))  # telemetry_service returns most-recent-first


def _stable_history(n: int = 12, workload_id: str = "wl-test-001") -> list[dict]:
    """Flat, healthy telemetry (most recent first)."""
    chrono = [_snapshot_dict(workload_id=workload_id, index=i) for i in range(n)]
    return list(reversed(chrono))


# --------------------------------------------------------------------------- #
# Predictor: output completeness (Property 14 by example)
# --------------------------------------------------------------------------- #
def test_predict_output_is_complete_and_in_bounds():
    prediction = predictor.predict("wl-test-001", _degrading_history())

    assert 0.0 <= prediction.probability <= 100.0
    assert prediction.primary_signal  # non-empty
    assert prediction.confidence in _CONFIDENCE_LEVELS
    assert len(prediction.risk_timeline) == 12
    assert all(isinstance(p, (int, float)) for p in prediction.risk_timeline)
    assert all(0.0 <= p <= 100.0 for p in prediction.risk_timeline)


def test_degrading_workload_is_high_probability_with_preemptive_action():
    prediction = predictor.predict("wl-test-001", _degrading_history())

    assert prediction.probability > 70.0
    # preemptive action present iff probability > 70%
    assert prediction.recommended_preemptive_action is not None
    assert prediction.estimated_time_to_failure


def test_stable_workload_is_low_probability_without_preemptive_action():
    prediction = predictor.predict("wl-test-001", _stable_history())

    assert prediction.probability <= 70.0
    assert prediction.recommended_preemptive_action is None


def test_preemptive_action_present_iff_probability_over_threshold():
    high = predictor.predict("wl-test-001", _degrading_history())
    low = predictor.predict("wl-test-001", _stable_history())

    assert (high.recommended_preemptive_action is not None) == (high.probability > 70.0)
    assert (low.recommended_preemptive_action is not None) == (low.probability > 70.0)


def test_confidence_scales_with_history_depth():
    assert predictor.predict("w", _stable_history(n=2)).confidence == "low"
    assert predictor.predict("w", _stable_history(n=5)).confidence == "medium"
    assert predictor.predict("w", _stable_history(n=10)).confidence == "high"


def test_low_confidence_caps_probability_and_suppresses_action():
    # Two points already near critical: without enough history we must not
    # fabricate a high-risk claim (SDD fallback) -> probability capped, no CTA.
    chrono = [
        _snapshot_dict(index=0, memory=90.0),
        _snapshot_dict(index=1, memory=99.0),
    ]
    history = list(reversed(chrono))
    prediction = predictor.predict("wl-test-001", history)

    assert prediction.confidence == "low"
    assert prediction.probability <= 70.0
    assert prediction.recommended_preemptive_action is None


def test_empty_history_returns_safe_fallback():
    prediction = predictor.predict("wl-test-001", [])

    assert prediction.probability == 0.0
    assert prediction.primary_signal  # non-empty fallback text
    assert prediction.confidence == "low"
    assert len(prediction.risk_timeline) == 12
    assert prediction.recommended_preemptive_action is None


# --------------------------------------------------------------------------- #
# Timeline
# --------------------------------------------------------------------------- #
def test_timeline_has_twelve_points_and_rises_under_degradation():
    prediction = predictor.predict("wl-test-001", _degrading_history())
    tl = prediction.risk_timeline

    assert len(tl) == 12
    # A degrading workload's risk should not decrease over the horizon.
    assert tl[-1] >= tl[0]


def test_build_risk_timeline_empty_trends_is_all_zero():
    assert timeline.build_risk_timeline([]) == [0.0] * 12


# --------------------------------------------------------------------------- #
# API endpoint
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _seed_workload_with_history(workload_id: str, history_chrono: list[dict]) -> None:
    workload = Workload(
        workload_id=workload_id,
        workload_name="Prediction Test Workload",
        workload_type="api-service",
        cloud_service_type="container",
        environment="staging",
        region="us-east-1",
        owner_team="platform-team",
        construction_workflow="project_management_dashboard",
        workflow_criticality="high",
        status="warning",
    )
    workload_service.upsert_workload(workload)
    for row in history_chrono:
        telemetry_service.persist_snapshot(TelemetrySnapshot(**row))


def test_prediction_endpoint_returns_complete_envelope(client):
    workload_id = "wl-pred-endpoint-001"
    # persist chronological order (oldest first); query returns most-recent-first
    chrono = list(reversed(_degrading_history(workload_id=workload_id)))
    _seed_workload_with_history(workload_id, chrono)

    resp = client.get(f"/api/workloads/{workload_id}/prediction")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True

    data = body["data"]
    assert data["workload_id"] == workload_id
    assert 0.0 <= data["probability"] <= 100.0
    assert data["primary_signal"]
    assert data["confidence"] in _CONFIDENCE_LEVELS
    assert len(data["risk_timeline"]) == 12
    assert (data["recommended_preemptive_action"] is not None) == (
        data["probability"] > 70.0
    )


def test_prediction_endpoint_unknown_workload_404(client):
    resp = client.get("/api/workloads/wl-does-not-exist/prediction")
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"


def teardown_module(module):  # noqa: D401 - pytest hook
    """Remove the temp DB directory created for this module."""
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
