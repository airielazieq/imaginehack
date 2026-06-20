"""Property-based tests for telemetry validation (task 1.3).

**Property 1: Telemetry Validation Invariant**

For any TelemetrySnapshot, the ingestion endpoint SHALL accept it if and only if
all numeric fields are within their defined bounds (cpu/memory/error_rate in
[0, 100], counts and resource values >= 0, cost fields in [0, 999999.99]), and
SHALL reject it with a validation error otherwise. The validation decision must
be deterministic for the same input.

**Validates: Requirements 1.1, 1.2**

This module exercises the property at two levels:

1. *Model level* - constructing :class:`TelemetrySnapshot` directly. In-bounds
   field values construct successfully; an out-of-bounds value (one field beyond
   its min/max) raises ``pydantic.ValidationError``.
2. *API level* - POSTing to ``/api/telemetry/ingest``. In-bounds snapshots are
   accepted (HTTP 200) against a seeded workload; out-of-bounds snapshots are
   rejected with HTTP 422 and the structured ``VALIDATION_ERROR`` envelope.

An isolated temp SQLite DB is configured via ``CLOVER_DB_PATH`` before the app is
imported so tests never touch the real ``clover.db``.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_proptest_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.core.database import connection  # noqa: E402
from backend.main import app  # noqa: E402
from backend.schemas.telemetry import TelemetrySnapshot  # noqa: E402

# Cost bound mirrored from the schema.
_COST_MAX = 999999.99
# Generous upper cap for unbounded (>= 0) numeric fields to keep examples sane.
_UNBOUNDED_MAX = 1_000_000.0

_SEEDED_WORKLOAD = "wl-prop-001"


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------
def _pct():
    """A valid percentage value in [0, 100]."""
    return st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False)


def _nonneg_float():
    """A valid non-negative float in [0, _UNBOUNDED_MAX]."""
    return st.floats(
        min_value=0, max_value=_UNBOUNDED_MAX, allow_nan=False, allow_infinity=False
    )


def _cost():
    """A valid cost value in [0, _COST_MAX]."""
    return st.floats(
        min_value=0, max_value=_COST_MAX, allow_nan=False, allow_infinity=False
    )


def _nonneg_int():
    """A valid non-negative integer count."""
    return st.integers(min_value=0, max_value=10_000_000)


@st.composite
def valid_snapshots(draw, workload_id: str = _SEEDED_WORKLOAD):
    """Generate a fully in-bounds TelemetrySnapshot payload dict."""
    return {
        "workload_id": workload_id,
        "cpu_usage_percent": draw(_pct()),
        "memory_usage_percent": draw(_pct()),
        "storage_gb": draw(_nonneg_float()),
        "runtime_hours_24h": draw(_nonneg_float()),
        "request_count_24h": draw(_nonneg_int()),
        "error_rate_percent": draw(_pct()),
        "latency_ms": draw(_nonneg_float()),
        "public_exposure": draw(st.booleans()),
        "public_storage": draw(st.booleans()),
        "vulnerability_severity": draw(
            st.sampled_from(["none", "low", "medium", "high", "critical"])
        ),
        "critical_vulnerability_count": draw(_nonneg_int()),
        "access_anomaly_detected": draw(st.booleans()),
        "monitoring_enabled": draw(st.booleans()),
        "cost_per_hour": draw(_cost()),
        "cost_24h": draw(_cost()),
        "cost_30d_forecast": draw(_cost()),
        "energy_kwh_24h": draw(_nonneg_float()),
        "carbon_kgco2e_24h": draw(_nonneg_float()),
        "carbon_intensity_gco2_per_kwh": draw(_nonneg_float()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# Percentage fields are bounded [0, 100]; an out-of-bounds value is < 0 or > 100.
_PERCENT_FIELDS = ["cpu_usage_percent", "memory_usage_percent", "error_rate_percent"]
# Non-negative float fields; out-of-bounds means < 0.
_NONNEG_FLOAT_FIELDS = [
    "storage_gb",
    "runtime_hours_24h",
    "latency_ms",
    "energy_kwh_24h",
    "carbon_kgco2e_24h",
    "carbon_intensity_gco2_per_kwh",
]
# Non-negative integer fields; out-of-bounds means < 0.
_NONNEG_INT_FIELDS = ["request_count_24h", "critical_vulnerability_count"]
# Cost fields bounded [0, _COST_MAX]; out-of-bounds means < 0 or > _COST_MAX.
_COST_FIELDS = ["cost_per_hour", "cost_24h", "cost_30d_forecast"]


def _out_of_bounds_overrides():
    """Strategy producing a (field, out_of_bounds_value) override pair."""
    below_zero_f = st.floats(
        min_value=-_UNBOUNDED_MAX, max_value=-0.001, allow_nan=False, allow_infinity=False
    )
    above_hundred = st.floats(
        min_value=100.001, max_value=_UNBOUNDED_MAX, allow_nan=False, allow_infinity=False
    )
    above_cost = st.floats(
        min_value=_COST_MAX + 0.011,
        max_value=_COST_MAX * 1000,
        allow_nan=False,
        allow_infinity=False,
    )
    neg_int = st.integers(min_value=-10_000_000, max_value=-1)

    return st.one_of(
        st.tuples(st.sampled_from(_PERCENT_FIELDS), st.one_of(below_zero_f, above_hundred)),
        st.tuples(st.sampled_from(_NONNEG_FLOAT_FIELDS), below_zero_f),
        st.tuples(st.sampled_from(_NONNEG_INT_FIELDS), neg_int),
        st.tuples(st.sampled_from(_COST_FIELDS), st.one_of(below_zero_f, above_cost)),
    )


@st.composite
def out_of_bounds_snapshots(draw, workload_id: str = _SEEDED_WORKLOAD):
    """A valid snapshot with exactly one numeric field pushed out of bounds."""
    snapshot = draw(valid_snapshots(workload_id=workload_id))
    field, value = draw(_out_of_bounds_overrides())
    snapshot[field] = value
    return snapshot


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    """TestClient with lifespan active; seeds the workload used by API examples."""
    with TestClient(app) as c:
        with connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO workloads "
                "(workload_id, workload_name, workload_type, cloud_service_type, "
                " environment, workflow_criticality, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _SEEDED_WORKLOAD,
                    "Property Test Workload",
                    "test",
                    "vm",
                    "testing",
                    "low",
                    "healthy",
                ),
            )
        yield c


# ---------------------------------------------------------------------------
# Property 1 - model level
# ---------------------------------------------------------------------------
@settings(max_examples=100, deadline=None)
@given(payload=valid_snapshots())
def test_in_bounds_snapshot_constructs(payload):
    """In-bounds field values always build a valid TelemetrySnapshot."""
    snapshot = TelemetrySnapshot(**payload)
    assert 0 <= snapshot.cpu_usage_percent <= 100
    assert 0 <= snapshot.memory_usage_percent <= 100
    assert 0 <= snapshot.error_rate_percent <= 100
    assert snapshot.storage_gb >= 0
    assert snapshot.request_count_24h >= 0
    assert 0 <= snapshot.cost_24h <= _COST_MAX


@settings(max_examples=100, deadline=None)
@given(payload=out_of_bounds_snapshots())
def test_out_of_bounds_snapshot_raises(payload):
    """Any single out-of-bounds numeric field raises ValidationError."""
    with pytest.raises(ValidationError):
        TelemetrySnapshot(**payload)


# ---------------------------------------------------------------------------
# Property 1 - API level
# ---------------------------------------------------------------------------
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(payload=valid_snapshots())
def test_api_accepts_in_bounds(client, payload):
    """The ingestion endpoint accepts in-bounds snapshots with HTTP 200."""
    resp = client.post("/api/telemetry/ingest", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["workload_id"] == _SEEDED_WORKLOAD


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(payload=out_of_bounds_snapshots())
def test_api_rejects_out_of_bounds(client, payload):
    """The ingestion endpoint rejects out-of-bounds snapshots with HTTP 422.

    The response follows the structured error envelope:
    ``{"error": true, "code": "VALIDATION_ERROR", ...}``.
    """
    resp = client.post("/api/telemetry/ingest", json=payload)
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error"] is True
    assert body["code"] == "VALIDATION_ERROR"
