"""Tests for the audit log API (task 15.2).

Covers Requirements 15.1 and 21.1 (spec 10 §5):

- GET /api/audit-logs               -> list audit entries (most recent first),
  filterable by workload_id, event_type and an inclusive start/end date window.
- GET /api/audit-logs/{id}          -> single audit entry (found + 404).
- GET /api/issues/{id}/audit-logs   -> all audit entries for an issue.

The list/detail endpoints return the audit data directly in ``data`` (a bare
``AuditLog[]`` for the list endpoints, a single ``AuditLog`` for the detail
endpoint) to match the frontend's ``getAuditLogs`` / ``getAuditLog`` /
``getIssueAuditLogs`` typings.

A temporary SQLite database is configured via ``CLOVER_DB_PATH`` before the app
is imported so tests never touch the real ``clover.db``. Entries are seeded
directly through the audit service against that same DB.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_audit_api_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.services import audit_service  # noqa: E402

# Unique workload ids so the assertions are robust against any audit entries
# the application lifespan might write during startup.
_WL = "wl-audit-api-001"
_WL_OTHER = "wl-audit-api-002"
_BASE = datetime(2024, 3, 1, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def seeded(client):
    """Seed a known set of audit entries into the isolated DB."""
    detected = audit_service.write_audit_log(
        event_type="issue_detected",
        actor="system",
        workload_id=_WL,
        issue_id="iss-audit-1",
        new_status="new",
        details={"severity": "high"},
        timestamp=_BASE,
    )
    recommended = audit_service.write_audit_log(
        event_type="recommendation_generated",
        actor="system",
        workload_id=_WL,
        issue_id="iss-audit-1",
        recommendation_id="rec-audit-1",
        previous_status="new",
        new_status="recommended",
        timestamp=_BASE + timedelta(hours=1),
    )
    other = audit_service.write_audit_log(
        event_type="issue_detected",
        actor="system",
        workload_id=_WL_OTHER,
        issue_id="iss-audit-2",
        new_status="new",
        timestamp=_BASE + timedelta(hours=2),
    )
    return {"detected": detected, "recommended": recommended, "other": other}


@pytest.fixture(scope="module")
def client():
    """TestClient with lifespan active (creates schema in the temp DB)."""
    with TestClient(app) as c:
        yield c


def _data(resp):
    """Assert a 200 + success envelope and return the ``data`` payload."""
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert "data" in body
    return body["data"]


# --- GET /api/audit-logs -----------------------------------------------------
def test_list_returns_bare_list_most_recent_first(client, seeded):
    data = _data(client.get("/api/audit-logs"))
    # The list endpoint returns a bare list in `data` (not a {audit_logs} wrap).
    assert isinstance(data, list)

    ids = {entry["audit_id"] for entry in data}
    assert seeded["detected"].audit_id in ids
    assert seeded["recommended"].audit_id in ids
    assert seeded["other"].audit_id in ids

    timestamps = [entry["timestamp"] for entry in data]
    assert timestamps == sorted(timestamps, reverse=True)


def test_list_filter_by_workload_id(client, seeded):
    data = _data(client.get("/api/audit-logs", params={"workload_id": _WL}))
    assert isinstance(data, list)
    assert len(data) == 2
    assert {entry["workload_id"] for entry in data} == {_WL}


def test_list_filter_by_event_type(client, seeded):
    data = _data(
        client.get(
            "/api/audit-logs",
            params={"workload_id": _WL, "event_type": "recommendation_generated"},
        )
    )
    assert len(data) == 1
    assert data[0]["audit_id"] == seeded["recommended"].audit_id
    assert data[0]["event_type"] == "recommendation_generated"


def test_list_filter_by_date_range(client, seeded):
    data = _data(
        client.get(
            "/api/audit-logs",
            params={
                "workload_id": _WL,
                "start_date": (_BASE + timedelta(minutes=30)).isoformat(),
                "end_date": (_BASE + timedelta(hours=1, minutes=30)).isoformat(),
            },
        )
    )
    assert len(data) == 1
    assert data[0]["audit_id"] == seeded["recommended"].audit_id


# --- GET /api/audit-logs/{audit_id} -----------------------------------------
def test_get_single_found(client, seeded):
    audit_id = seeded["detected"].audit_id
    data = _data(client.get(f"/api/audit-logs/{audit_id}"))
    assert isinstance(data, dict)
    assert data["audit_id"] == audit_id
    assert data["workload_id"] == _WL
    assert data["event_type"] == "issue_detected"
    assert data["details"]["severity"] == "high"


def test_get_single_not_found_returns_404_envelope(client, seeded):
    resp = client.get("/api/audit-logs/AUDIT-DOESNOTEXIST")
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["error"] is True
    assert body["code"] == "NOT_FOUND"
    assert "AUDIT-DOESNOTEXIST" in body["message"]


# --- GET /api/issues/{issue_id}/audit-logs ----------------------------------
def test_list_for_issue(client, seeded):
    data = _data(client.get("/api/issues/iss-audit-1/audit-logs"))
    assert isinstance(data, list)
    assert len(data) == 2
    assert {entry["issue_id"] for entry in data} == {"iss-audit-1"}
    timestamps = [entry["timestamp"] for entry in data]
    assert timestamps == sorted(timestamps, reverse=True)


def test_list_for_issue_empty(client, seeded):
    data = _data(client.get("/api/issues/iss-does-not-exist/audit-logs"))
    assert data == []


def teardown_module(module):  # noqa: D401 - pytest hook
    """Remove the temp DB directory created for this module."""
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
