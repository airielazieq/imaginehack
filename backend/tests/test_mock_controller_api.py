"""Tests for the mock controller API (task 2.3).

Covers the demo-control endpoint group (Requirements 19.1-19.4):
- GET  /api/mock/scenarios            -> list 7 scenarios (no payload)
- POST /api/mock/trigger/{scenarioId} -> inject telemetry + 404 for unknown
- POST /api/mock/reset                -> reset to healthy baseline
- POST /api/mock/stream/start|stop    -> toggle the live stream
- GET  /api/mock/status               -> stream status
- App lifespan seeds workloads + baseline on startup.

A temporary SQLite database is configured via ``CLOVER_DB_PATH`` before the app
is imported so tests never touch the real ``clover.db``.
"""

from __future__ import annotations

import os
import tempfile

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_mockapi_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services import telemetry_service  # noqa: E402


@pytest.fixture(scope="module")
def client():
    """TestClient with lifespan active (seeds workloads + baseline)."""
    with TestClient(app) as c:
        yield c


# --- Lifespan seeding (Requirement 19.1) ------------------------------------
def test_lifespan_seeds_workloads(client):
    resp = client.get("/api/workloads")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["count"] >= 8


# --- GET /api/mock/scenarios -------------------------------------------------
def test_list_scenarios_returns_seven(client):
    resp = client.get("/api/mock/scenarios")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["count"] == 7
    assert len(body["data"]["scenarios"]) == 7
    sample = body["data"]["scenarios"][0]
    assert "scenario_id" in sample
    assert "telemetry" not in sample  # payload withheld from the list view


# --- POST /api/mock/trigger/{scenarioId} (Requirement 19.2) -----------------
def test_trigger_valid_scenario_persists_telemetry(client):
    resp = client.post("/api/mock/trigger/trigger_idle_dev_server")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    workload_id = body["data"]["workload_id"]
    assert workload_id == "wl-bim-processor-001"
    assert "telemetry_id" in body["data"]

    # Telemetry was persisted for the targeted workload.
    history = telemetry_service.get_telemetry_history(workload_id, limit=1)
    assert len(history) == 1
    assert history[0]["cpu_usage_percent"] == pytest.approx(4.0)


def test_trigger_unknown_scenario_returns_404_envelope(client):
    resp = client.post("/api/mock/trigger/does_not_exist")
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["error"] is True
    assert body["code"] == "NOT_FOUND"
    assert "does_not_exist" in body["message"]


# --- POST /api/mock/reset (Requirement 19.4) --------------------------------
def test_reset_restores_healthy_baseline(client):
    # Trigger a cost spike, then reset.
    client.post("/api/mock/trigger/trigger_cost_spike")
    resp = client.post("/api/mock/reset")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["baseline_snapshots"] >= 8

    # Triggered scenarios cleared after reset.
    status_resp = client.get("/api/mock/status")
    assert status_resp.json()["data"]["triggered_scenarios"] == []

    # Freshest snapshot for the cost-spike target is back to healthy baseline.
    history = telemetry_service.get_telemetry_history("wl-costly-vm-001", limit=1)
    assert history[0]["cost_30d_forecast"] == pytest.approx(324.0)


# --- Stream start/stop/status (Requirement 19.3) ----------------------------
def test_stream_start_stop_and_status(client):
    start = client.post("/api/mock/stream/start")
    assert start.status_code == 200, start.text
    assert start.json()["data"]["streaming"] is True

    status_resp = client.get("/api/mock/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["data"]["streaming"] is True

    stop = client.post("/api/mock/stream/stop")
    assert stop.status_code == 200, stop.text
    assert stop.json()["data"]["streaming"] is False

    # Stopping again is a no-op.
    stop_again = client.post("/api/mock/stream/stop")
    assert stop_again.json()["data"]["stopped"] is False
