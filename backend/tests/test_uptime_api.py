"""Tests for the 90-day uptime history endpoint (task 8.2).

Covers Requirement 17.3 (90-day uptime bar / historical availability segments):
- GET /api/workloads/{id}/uptime returns exactly 90 daily segments with a
  valid success envelope and an overall uptime percentage summary.
- The synthetic history is deterministic per workload (identical across two
  calls).
- An unknown workload returns the NOT_FOUND error envelope (HTTP 404).

A temporary SQLite database is configured via ``CLOVER_DB_PATH`` before the app
is imported so tests never touch the real ``clover.db``.
"""

from __future__ import annotations

import os
import tempfile

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="clover_uptime_test_"), "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

import pytest  # noqa: E402

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.schemas.workload import Workload  # noqa: E402
from backend.services import workload_service  # noqa: E402


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


@pytest.fixture(scope="module")
def client():
    """TestClient with lifespan active (creates schema in the temp DB)."""
    with TestClient(app) as c:
        workload_service.upsert_workload(_make_workload("wl-uptime-001"))
        workload_service.upsert_workload(_make_workload("wl-uptime-002"))
        yield c


def test_uptime_returns_ninety_segments_with_envelope(client):
    resp = client.get("/api/workloads/wl-uptime-001/uptime")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["workload_id"] == "wl-uptime-001"
    assert data["count"] == 90
    assert data["window_days"] == 90
    segments = data["segments"]
    assert len(segments) == 90


def test_uptime_segments_are_valid(client):
    resp = client.get("/api/workloads/wl-uptime-001/uptime")
    data = resp.json()["data"]
    segments = data["segments"]

    valid_statuses = {"up", "degraded", "down"}
    for seg in segments:
        assert set(seg.keys()) >= {"date", "uptime_percent", "status"}
        assert seg["status"] in valid_statuses
        assert 0.0 <= seg["uptime_percent"] <= 100.0

    # Dates are ascending (oldest first) and unique.
    dates = [seg["date"] for seg in segments]
    assert dates == sorted(dates)
    assert len(set(dates)) == 90

    # Overall summary is a plausible percentage.
    assert 0.0 <= data["overall_uptime_percent"] <= 100.0


def test_uptime_is_deterministic_per_workload(client):
    first = client.get("/api/workloads/wl-uptime-001/uptime").json()["data"]
    second = client.get("/api/workloads/wl-uptime-001/uptime").json()["data"]
    # Identical across calls (RNG seeded by workload_id).
    assert first["segments"] == second["segments"]
    assert first["overall_uptime_percent"] == second["overall_uptime_percent"]


def test_uptime_differs_between_workloads(client):
    one = client.get("/api/workloads/wl-uptime-001/uptime").json()["data"]
    two = client.get("/api/workloads/wl-uptime-002/uptime").json()["data"]
    # Different seeds should (overwhelmingly likely) produce different history.
    assert one["segments"] != two["segments"]


def test_uptime_unknown_workload_returns_404(client):
    resp = client.get("/api/workloads/does-not-exist/uptime")
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["error"] is True
    assert body["code"] == "NOT_FOUND"
    assert "does-not-exist" in body["message"]
