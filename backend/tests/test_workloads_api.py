"""Tests for the workloads API (task 1.6).

Covers Requirement 21.1 (workloads endpoint group):
- GET /api/workloads              -> list all workloads
- GET /api/workloads/{id}         -> single workload (found + 404)
- GET /api/workloads/{id}/telemetry -> telemetry history, most recent first,
  with optional limit; 404 for an unknown workload.

A temporary SQLite database is configured via ``CLOVER_DB_PATH`` before the app
is imported so tests never touch the real ``clover.db``.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="clover_wl_test_"), "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.schemas.telemetry import TelemetrySnapshot  # noqa: E402
from backend.schemas.workload import Workload  # noqa: E402
from backend.services import telemetry_service, workload_service  # noqa: E402


def _make_workload(workload_id: str, **overrides) -> Workload:
    payload = {
        "workload_id": workload_id,
        "workload_name": f"Workload {workload_id}",
        "workload_type": "compute",
        "cloud_service_type": "vm",
        "environment": "development",
        "region": "us-east-1",
        "owner_team": "platform",
        "construction_workflow": "bim_model_data_processing",
        "workflow_criticality": "medium",
        "status": "healthy",
    }
    payload.update(overrides)
    return Workload(**payload)


def _make_snapshot(workload_id: str, ts: datetime, **overrides) -> TelemetrySnapshot:
    payload = {
        "workload_id": workload_id,
        "cpu_usage_percent": 30.0,
        "memory_usage_percent": 40.0,
        "storage_gb": 50.0,
        "runtime_hours_24h": 24.0,
        "request_count_24h": 1000,
        "error_rate_percent": 0.5,
        "latency_ms": 50.0,
        "public_exposure": False,
        "public_storage": False,
        "vulnerability_severity": "none",
        "critical_vulnerability_count": 0,
        "access_anomaly_detected": False,
        "monitoring_enabled": True,
        "cost_per_hour": 1.0,
        "cost_24h": 24.0,
        "cost_30d_forecast": 720.0,
        "energy_kwh_24h": 10.0,
        "carbon_kgco2e_24h": 3.0,
        "carbon_intensity_gco2_per_kwh": 300.0,
        "timestamp": ts.isoformat(),
    }
    payload.update(overrides)
    return TelemetrySnapshot(**payload)


@pytest.fixture(scope="module")
def client():
    """TestClient with lifespan active (creates schema in the temp DB)."""
    with TestClient(app) as c:
        # Seed two workloads.
        workload_service.upsert_workload(_make_workload("wl-alpha-001"))
        workload_service.upsert_workload(
            _make_workload("wl-beta-002", environment="production", status="warning")
        )
        # Seed telemetry for wl-alpha-001 at increasing timestamps.
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(3):
            telemetry_service.persist_snapshot(
                _make_snapshot(
                    "wl-alpha-001",
                    base + timedelta(hours=i),
                    cpu_usage_percent=float(10 * (i + 1)),
                )
            )
        yield c


# --- GET /api/workloads ------------------------------------------------------
def test_list_workloads_returns_all(client):
    resp = client.get("/api/workloads")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    ids = {w["workload_id"] for w in body["data"]["workloads"]}
    # The app lifespan seeds the canonical sample workloads on startup, so the
    # list contains those plus the two seeded by this test fixture.
    assert {"wl-alpha-001", "wl-beta-002"}.issubset(ids)
    assert body["data"]["count"] == len(ids)


# --- GET /api/workloads/{id} -------------------------------------------------
def test_get_workload_found(client):
    resp = client.get("/api/workloads/wl-beta-002")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["workload_id"] == "wl-beta-002"
    assert body["data"]["environment"] == "production"
    assert body["data"]["status"] == "warning"


def test_get_workload_not_found_returns_404_envelope(client):
    resp = client.get("/api/workloads/does-not-exist")
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["error"] is True
    assert body["code"] == "NOT_FOUND"
    assert "does-not-exist" in body["message"]


# --- GET /api/workloads/{id}/telemetry --------------------------------------
def test_get_telemetry_history_most_recent_first(client):
    resp = client.get("/api/workloads/wl-alpha-001/telemetry")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["workload_id"] == "wl-alpha-001"
    assert body["data"]["count"] == 3
    history = body["data"]["telemetry"]
    timestamps = [snap["timestamp"] for snap in history]
    # Most recent first (descending).
    assert timestamps == sorted(timestamps, reverse=True)


def test_get_telemetry_history_respects_limit(client):
    resp = client.get("/api/workloads/wl-alpha-001/telemetry?limit=2")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["count"] == 2
    history = body["data"]["telemetry"]
    # The two most recent snapshots only.
    timestamps = [snap["timestamp"] for snap in history]
    assert timestamps == sorted(timestamps, reverse=True)


def test_get_telemetry_history_empty_for_workload_without_telemetry(client):
    resp = client.get("/api/workloads/wl-beta-002/telemetry")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["count"] == 0
    assert body["data"]["telemetry"] == []


def test_get_telemetry_history_unknown_workload_returns_404(client):
    resp = client.get("/api/workloads/does-not-exist/telemetry")
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["error"] is True
    assert body["code"] == "NOT_FOUND"


def test_telemetry_limit_validation_rejects_zero(client):
    resp = client.get("/api/workloads/wl-alpha-001/telemetry?limit=0")
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
