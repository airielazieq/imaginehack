"""Tests for the detection orchestrator + Issues API (task 3.5).

Covers Requirements 2.1, 2.4, 3.3, 18.1, 18.2 end to end:

- Triggering a mock scenario flows telemetry -> detection (via the
  TELEMETRY_INGESTED subscription and/or the synchronous run endpoint) and
  produces a correctly classified Issue with a non-null ml_result,
  xai_explanation, and llm_user_explanation.
- GET /api/issues lists/filters issues; GET /api/issues/{id} returns detail;
  PATCH /api/issues/{id}/status transitions status.
- Re-running detection for the same workload within the 5-minute window
  consolidates into a single Issue carrying the maximum severity.
- A healthy baseline snapshot produces no Issue.

An isolated temp SQLite DB is configured via CLOVER_DB_PATH before the app is
imported so tests never touch the real clover.db.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_detection_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.schemas.telemetry import TelemetrySnapshot  # noqa: E402
from backend.services import issue_service, telemetry_service  # noqa: E402


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


def _healthy_snapshot(workload_id: str, *, ts: datetime | None = None) -> dict:
    """A plainly-healthy telemetry payload that fires no detection rule.

    The timestamp defaults to "now" so the snapshot is the freshest reading for
    its workload (the detection-run endpoint always scores the latest snapshot).
    Real-clock timestamps keep this consistent with the other test modules that
    share the process-wide test database.
    """
    timestamp = ts or datetime.now(timezone.utc)
    return {
        "workload_id": workload_id,
        "cpu_usage_percent": 45.0,
        "memory_usage_percent": 55.0,
        "storage_gb": 100.0,
        "runtime_hours_24h": 8.0,
        "request_count_24h": 50000,
        "error_rate_percent": 0.4,
        "latency_ms": 120.0,
        "public_exposure": False,
        "public_storage": False,
        "vulnerability_severity": "none",
        "critical_vulnerability_count": 0,
        "access_anomaly_detected": False,
        "monitoring_enabled": True,
        "cost_per_hour": 0.5,
        "cost_24h": 12.0,
        "cost_30d_forecast": 360.0,
        "energy_kwh_24h": 14.0,
        "carbon_kgco2e_24h": 5.6,
        "carbon_intensity_gco2_per_kwh": 400.0,
        "timestamp": timestamp.isoformat(),
    }


# --------------------------------------------------------------------------- #
# Scenario -> detection -> Issue (Requirements 2.1, 18.1)
# --------------------------------------------------------------------------- #
def test_trigger_scenario_then_run_creates_classified_issue(client):
    # Trigger the cost-spike scenario (targets wl-costly-vm-001).
    trig = client.post("/api/mock/trigger/trigger_cost_spike")
    assert trig.status_code == 200, trig.text
    workload_id = trig.json()["data"]["workload_id"]
    assert workload_id == "wl-costly-vm-001"

    # Run detection synchronously on the latest telemetry (deterministic).
    run = client.post(f"/api/detection/run/{workload_id}")
    assert run.status_code == 200, run.text
    data = run.json()["data"]
    assert data["detected"] is True
    issue = data["issue"]

    # Correct classification for a cost spike.
    assert issue["issue_type"] == "cost_spike_or_waste"
    assert issue["issue_category"] == "cost"
    assert issue["severity"] in {"low", "medium", "high", "critical"}
    assert 0.0 <= issue["confidence_score"] <= 1.0

    # Detection output structure: ml_result + xai + llm explanation all present.
    assert issue["ml_result"] is not None
    assert issue["ml_result"]["model_name"]
    assert issue["xai_explanation"] is not None
    assert len(issue["xai_explanation"]["top_contributing_factors"]) >= 3
    assert isinstance(issue["llm_user_explanation"], str)
    assert issue["llm_user_explanation"].strip()
    assert issue["estimated_impact"] is not None

    # GET /api/issues returns the issue.
    listed = client.get("/api/issues", params={"workload_id": workload_id})
    assert listed.status_code == 200
    ids = [i["issue_id"] for i in listed.json()["data"]["issues"]]
    assert issue["issue_id"] in ids


def test_run_detection_all_produces_issue_for_triggered_workload(client):
    client.post("/api/mock/trigger/trigger_high_error_rate")
    run = client.post("/api/detection/run")
    assert run.status_code == 200, run.text
    issues = run.json()["data"]["issues"]
    perf = [i for i in issues if i["workload_id"] == "wl-iot-dashboard-001"]
    assert perf, "expected a high_error_rate issue for the iot dashboard"
    assert perf[0]["issue_type"] == "high_error_rate"
    assert perf[0]["issue_category"] == "performance"


# --------------------------------------------------------------------------- #
# Subscription wiring: trigger alone (no explicit run) creates an Issue (2.4)
# --------------------------------------------------------------------------- #
def test_subscription_creates_issue_without_explicit_run(client):
    # The mock trigger emits TELEMETRY_INGESTED; the subscribed detector reacts.
    client.post("/api/mock/trigger/trigger_missing_monitoring")
    # A follow-up request lets the event loop drain the background detection task.
    client.get("/api/mock/status")

    issues = issue_service.list_issues(workload_id="wl-ci-pipeline-001")
    assert issues, "subscription should have produced an issue for the CI pipeline"
    assert issues[0]["issue_type"] == "no_monitoring"
    assert issues[0]["issue_category"] == "monitoring"


# --------------------------------------------------------------------------- #
# Consolidation within 5 minutes -> single Issue, max severity (Req 3.3)
# --------------------------------------------------------------------------- #
def test_consolidation_keeps_single_issue_with_max_severity(client):
    workload_id = "wl-bim-processor-001"  # development, medium criticality
    now = datetime.now(timezone.utc)

    # First detection: idle/overprovisioned -> medium severity.
    idle = _healthy_snapshot(workload_id, ts=now + timedelta(seconds=1))
    idle.update({"cpu_usage_percent": 4.0, "runtime_hours_24h": 24.0})
    telemetry_service.persist_snapshot(TelemetrySnapshot(**idle))
    first = client.post(f"/api/detection/run/{workload_id}")
    assert first.status_code == 200, first.text
    first_issue = first.json()["data"]["issue"]
    assert first_issue["issue_type"] == "idle_or_overprovisioned_workload"
    first_issue_id = first_issue["issue_id"]
    medium_rank = issue_service.severity_rank(first_issue["severity"])

    # Second detection within the window: public storage -> high severity.
    storage = _healthy_snapshot(workload_id, ts=now + timedelta(seconds=2))
    storage.update({"public_storage": True})
    telemetry_service.persist_snapshot(TelemetrySnapshot(**storage))
    second = client.post(f"/api/detection/run/{workload_id}")
    assert second.status_code == 200, second.text
    second_issue = second.json()["data"]["issue"]

    # Same Issue id (consolidated, not duplicated) and severity escalated to max.
    assert second_issue["issue_id"] == first_issue_id
    assert issue_service.severity_rank(second_issue["severity"]) >= medium_rank
    assert second_issue["severity"] == "high"

    # Exactly one issue persisted for the workload.
    open_issues = issue_service.list_issues(workload_id=workload_id)
    assert len(open_issues) == 1


# --------------------------------------------------------------------------- #
# Healthy baseline -> no Issue
# --------------------------------------------------------------------------- #
def test_healthy_snapshot_produces_no_issue(client):
    workload_id = "wl-safety-analytics-001"
    telemetry_service.persist_snapshot(TelemetrySnapshot(**_healthy_snapshot(workload_id)))
    run = client.post(f"/api/detection/run/{workload_id}")
    assert run.status_code == 200, run.text
    data = run.json()["data"]
    assert data["detected"] is False
    assert data["issue"] is None
    assert issue_service.list_issues(workload_id=workload_id) == []


# --------------------------------------------------------------------------- #
# Issues query surface (Requirements 18.1, 18.2)
# --------------------------------------------------------------------------- #
def test_get_issue_detail_and_404(client):
    client.post("/api/mock/trigger/trigger_cost_spike")
    issue = client.post("/api/detection/run/wl-costly-vm-001").json()["data"]["issue"]

    detail = client.get(f"/api/issues/{issue['issue_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["success"] is True
    assert body["data"]["issue_id"] == issue["issue_id"]
    assert body["data"]["ml_result"]["model_name"]

    missing = client.get("/api/issues/iss-does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"


def test_list_issues_filters(client):
    client.post("/api/mock/trigger/trigger_cost_spike")
    client.post("/api/detection/run/wl-costly-vm-001")
    client.post("/api/mock/trigger/trigger_high_error_rate")
    client.post("/api/detection/run/wl-iot-dashboard-001")

    # Filter by category.
    cost = client.get("/api/issues", params={"issue_category": "cost"})
    assert cost.status_code == 200
    assert all(i["issue_category"] == "cost" for i in cost.json()["data"]["issues"])
    assert cost.json()["data"]["count"] >= 1

    # Filter by issue_type.
    perf = client.get("/api/issues", params={"issue_type": "high_error_rate"})
    assert all(i["issue_type"] == "high_error_rate" for i in perf.json()["data"]["issues"])
    assert perf.json()["data"]["count"] >= 1


def test_patch_issue_status(client):
    client.post("/api/mock/trigger/trigger_cost_spike")
    issue = client.post("/api/detection/run/wl-costly-vm-001").json()["data"]["issue"]

    patched = client.patch(
        f"/api/issues/{issue['issue_id']}/status", json={"status": "dismissed"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["status"] == "dismissed"

    # Persisted.
    refetched = client.get(f"/api/issues/{issue['issue_id']}")
    assert refetched.json()["data"]["status"] == "dismissed"

    # Unknown issue -> 404.
    missing = client.patch("/api/issues/nope/status", json={"status": "dismissed"})
    assert missing.status_code == 404


def test_patch_issue_status_rejects_invalid_value(client):
    client.post("/api/mock/trigger/trigger_cost_spike")
    issue = client.post("/api/detection/run/wl-costly-vm-001").json()["data"]["issue"]
    bad = client.patch(
        f"/api/issues/{issue['issue_id']}/status", json={"status": "not_a_status"}
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "VALIDATION_ERROR"


def test_run_detection_unknown_workload_404(client):
    resp = client.post("/api/detection/run/wl-not-real")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def teardown_module(module):  # noqa: D401 - pytest hook
    """Remove the temp DB directory created for this module."""
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
