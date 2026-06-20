"""Tests for the telemetry ingestion API (task 1.5).

Covers Requirements 1.1-1.4:
- 1.1 valid snapshot validated + persisted
- 1.2 out-of-bounds -> HTTP 422 structured error envelope
- 1.3 TELEMETRY_INGESTED event emitted on accepted ingest
- 1.4 bulk ingest of many workloads without data loss

A temporary SQLite database is configured via the ``CLOVER_DB_PATH`` env var
before the application is imported so tests never touch the real ``clover.db``.
"""

from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timezone

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="clover_test_"), "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core import config as config_module  # noqa: E402
from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.core.database import connection  # noqa: E402
from backend.core.event_bus import Event, EventType, event_bus  # noqa: E402
from backend.main import app  # noqa: E402


def _valid_snapshot(workload_id: str = "wl-test-001", **overrides) -> dict:
    """Build a fully-valid TelemetrySnapshot payload dict."""
    snapshot = {
        "workload_id": workload_id,
        "cpu_usage_percent": 42.5,
        "memory_usage_percent": 63.0,
        "storage_gb": 120.0,
        "runtime_hours_24h": 24.0,
        "request_count_24h": 15000,
        "error_rate_percent": 1.2,
        "latency_ms": 85.0,
        "public_exposure": False,
        "public_storage": False,
        "vulnerability_severity": "low",
        "critical_vulnerability_count": 0,
        "access_anomaly_detected": False,
        "monitoring_enabled": True,
        "cost_per_hour": 1.25,
        "cost_24h": 30.0,
        "cost_30d_forecast": 900.0,
        "energy_kwh_24h": 12.5,
        "carbon_kgco2e_24h": 4.2,
        "carbon_intensity_gco2_per_kwh": 336.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    snapshot.update(overrides)
    return snapshot


def _seed_workload(workload_id: str) -> None:
    """Insert a minimal workload row so telemetry FK constraints are satisfied."""
    with connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO workloads "
            "(workload_id, workload_name, workload_type, cloud_service_type, "
            " environment, workflow_criticality, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                workload_id,
                f"Test {workload_id}",
                "test",
                "vm",
                "testing",
                "low",
                "healthy",
            ),
        )


@pytest.fixture(scope="module")
def client():
    """TestClient with lifespan active (creates schema in the temp DB).

    Seeds the workloads referenced by the ingest tests so the telemetry
    foreign-key constraint is satisfied (telemetry references an existing
    workload, per the data model).
    """
    with TestClient(app) as c:
        _seed_workload("wl-ingest-001")
        _seed_workload("wl-bulk-ok")
        for i in range(10):
            _seed_workload(f"wl-bulk-{i:03d}")
        yield c


def _telemetry_row_count(workload_id: str) -> int:
    with connection() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) AS n FROM telemetry WHERE workload_id = ?",
            (workload_id,),
        )
        return int(cur.fetchone()["n"])


# --- Requirement 1.1 / 1.3 ---------------------------------------------------
def test_ingest_valid_snapshot_persists_and_emits(client):
    captured: list[Event] = []

    async def _handler(event: Event) -> None:
        captured.append(event)

    event_bus.subscribe(EventType.TELEMETRY_INGESTED, _handler)
    try:
        wl = "wl-ingest-001"
        resp = client.post("/api/telemetry/ingest", json=_valid_snapshot(wl))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["workload_id"] == wl
        assert isinstance(body["data"]["telemetry_id"], int)

        # 1.1 persisted
        assert _telemetry_row_count(wl) == 1

        # 1.3 event emitted (background task; poll briefly)
        deadline = time.time() + 2.0
        while not captured and time.time() < deadline:
            time.sleep(0.02)
        assert len(captured) == 1
        evt = captured[0]
        assert evt.event_type == EventType.TELEMETRY_INGESTED
        assert evt.payload["workload_id"] == wl
        assert evt.payload["snapshot"]["cpu_usage_percent"] == 42.5
    finally:
        event_bus.unsubscribe(EventType.TELEMETRY_INGESTED, _handler)


# --- Requirement 1.2 ---------------------------------------------------------
@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("cpu_usage_percent", 150.0),
        ("memory_usage_percent", -1.0),
        ("error_rate_percent", 250.0),
        ("storage_gb", -5.0),
        ("cost_24h", 1_000_000.0),
        ("request_count_24h", -3),
    ],
)
def test_ingest_out_of_bounds_returns_422(client, field, bad_value):
    resp = client.post(
        "/api/telemetry/ingest", json=_valid_snapshot(**{field: bad_value})
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error"] is True
    assert body["code"] == "VALIDATION_ERROR"
    assert "details" in body


def test_ingest_missing_field_returns_422(client):
    payload = _valid_snapshot()
    del payload["latency_ms"]
    resp = client.post("/api/telemetry/ingest", json=payload)
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


# --- Requirement 1.4 ---------------------------------------------------------
def test_bulk_ingest_many_workloads(client):
    workloads = [f"wl-bulk-{i:03d}" for i in range(10)]
    payload = [_valid_snapshot(wl) for wl in workloads]
    resp = client.post("/api/telemetry/bulk-ingest", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["ingested_count"] == 10
    # No data loss: every workload has a persisted row.
    for wl in workloads:
        assert _telemetry_row_count(wl) == 1


def test_bulk_ingest_rejects_when_any_invalid(client):
    payload = [_valid_snapshot("wl-bulk-ok"), _valid_snapshot(cpu_usage_percent=500.0)]
    resp = client.post("/api/telemetry/bulk-ingest", json=payload)
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
