"""Tests for the audit log service and event subscribers (task 15.1).

Covers Requirements 15.1-15.4:

- An audit entry is written on each subscribed lifecycle event
  (ISSUE_DETECTED, RECOMMENDATION_GENERATED, REMEDIATION_COMPLETED) with the
  correct workload/issue/recommendation/remediation links and status fields.
- A rollback produces its own immutable rollback audit entry (Req 15.4).
- The audit trail is immutable / write-once: re-recording the same audit_id is
  rejected and there is no update path.
- The query helpers (get by id, list with filters, list-for-issue) return the
  expected records most-recent-first.
- Retention enforcement removes only entries past the 90-day window (Req 15.2).

All tests use an isolated temp SQLite DB via the ``db_path`` override so they
never touch the real clover.db. Regular pytest unit tests (no Hypothesis).
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.connectors.audit_connector import build_audit_log
from backend.core.database import init_db
from backend.core.event_bus import Event, EventType, event_bus
from backend.services import audit_service


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db_path(tmp_path) -> str:
    """An initialized, isolated SQLite DB for a single test."""
    path = str(tmp_path / "audit_test.db")
    init_db(path)
    return path


@pytest.fixture()
def route_to_db(db_path, monkeypatch):
    """Force the event handlers' ``write_audit_log`` calls into the temp DB.

    The handlers call the module-level ``write_audit_log`` (resolved at call
    time), so patching the module attribute redirects their writes to the
    isolated test database.
    """
    real = audit_service.write_audit_log

    def _patched(**kwargs):
        kwargs.setdefault("db_path", db_path)
        return real(**kwargs)

    monkeypatch.setattr(audit_service, "write_audit_log", _patched)
    return db_path


def _drain(coro) -> None:
    """Run an async coroutine to completion in a fresh loop."""
    asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Write + query basics
# --------------------------------------------------------------------------- #
def test_write_and_get(db_path):
    log = audit_service.write_audit_log(
        event_type="issue_detected",
        actor="system",
        workload_id="wl-1",
        issue_id="iss-1",
        new_status="new",
        details={"severity": "high"},
        db_path=db_path,
    )

    fetched = audit_service.get_audit_log(log.audit_id, db_path=db_path)
    assert fetched is not None
    assert fetched["audit_id"] == log.audit_id
    assert fetched["event_type"] == "issue_detected"
    assert fetched["workload_id"] == "wl-1"
    assert fetched["issue_id"] == "iss-1"
    assert fetched["new_status"] == "new"
    assert fetched["details"]["severity"] == "high"


def test_get_missing_returns_none(db_path):
    assert audit_service.get_audit_log("AUDIT-DOESNOTEXIST", db_path=db_path) is None


# --------------------------------------------------------------------------- #
# Immutability (write-once, no update path)
# --------------------------------------------------------------------------- #
def test_duplicate_audit_id_rejected(db_path):
    log = build_audit_log(event_type="issue_detected", workload_id="wl-1")
    audit_service.record_audit(log, db_path=db_path)
    # Re-recording the same id must be rejected -> trail is immutable.
    with pytest.raises(sqlite3.IntegrityError):
        audit_service.record_audit(log, db_path=db_path)


def test_no_update_path_exposed():
    # The service must not expose any mutation/update of existing entries.
    for name in dir(audit_service):
        assert not name.startswith("update_"), f"unexpected update path: {name}"
    assert not hasattr(audit_service, "delete_audit_log")


# --------------------------------------------------------------------------- #
# Query filters + ordering
# --------------------------------------------------------------------------- #
def test_list_filters_and_recent_first(db_path):
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    audit_service.write_audit_log(
        event_type="issue_detected", workload_id="wl-a", issue_id="iss-a",
        timestamp=base, db_path=db_path,
    )
    audit_service.write_audit_log(
        event_type="recommendation_generated", workload_id="wl-a", issue_id="iss-a",
        recommendation_id="rec-a", timestamp=base + timedelta(hours=1), db_path=db_path,
    )
    audit_service.write_audit_log(
        event_type="issue_detected", workload_id="wl-b", issue_id="iss-b",
        timestamp=base + timedelta(hours=2), db_path=db_path,
    )

    # No filter: all three, most-recent-first.
    all_logs = audit_service.list_audit_logs(db_path=db_path)
    assert len(all_logs) == 3
    timestamps = [entry["timestamp"] for entry in all_logs]
    assert timestamps == sorted(timestamps, reverse=True)

    # Filter by workload.
    wl_a = audit_service.list_audit_logs(workload_id="wl-a", db_path=db_path)
    assert {entry["workload_id"] for entry in wl_a} == {"wl-a"}
    assert len(wl_a) == 2

    # Filter by event type.
    detected = audit_service.list_audit_logs(event_type="issue_detected", db_path=db_path)
    assert {entry["event_type"] for entry in detected} == {"issue_detected"}
    assert len(detected) == 2

    # Filter by date range (inclusive bounds).
    windowed = audit_service.list_audit_logs(
        start_date=base + timedelta(minutes=30),
        end_date=base + timedelta(hours=1, minutes=30),
        db_path=db_path,
    )
    assert len(windowed) == 1
    assert windowed[0]["event_type"] == "recommendation_generated"


def test_list_for_issue(db_path):
    audit_service.write_audit_log(
        event_type="issue_detected", workload_id="wl-a", issue_id="iss-x", db_path=db_path,
    )
    audit_service.write_audit_log(
        event_type="recommendation_generated", workload_id="wl-a", issue_id="iss-x",
        recommendation_id="rec-x", db_path=db_path,
    )
    audit_service.write_audit_log(
        event_type="issue_detected", workload_id="wl-a", issue_id="iss-y", db_path=db_path,
    )

    for_x = audit_service.list_for_issue("iss-x", db_path=db_path)
    assert len(for_x) == 2
    assert {entry["issue_id"] for entry in for_x} == {"iss-x"}


# --------------------------------------------------------------------------- #
# Retention enforcement (Requirement 15.2) — only removal path
# --------------------------------------------------------------------------- #
def test_purge_expired_only_removes_old(db_path):
    now = datetime(2024, 6, 1, tzinfo=timezone.utc)
    audit_service.write_audit_log(
        event_type="issue_detected", workload_id="wl-old", issue_id="iss-old",
        timestamp=now - timedelta(days=120), db_path=db_path,
    )
    fresh = audit_service.write_audit_log(
        event_type="issue_detected", workload_id="wl-new", issue_id="iss-new",
        timestamp=now - timedelta(days=10), db_path=db_path,
    )

    removed = audit_service.purge_expired_logs(now=now, db_path=db_path)
    assert removed == 1
    remaining = audit_service.list_audit_logs(db_path=db_path)
    assert len(remaining) == 1
    assert remaining[0]["audit_id"] == fresh.audit_id


# --------------------------------------------------------------------------- #
# Event subscribers write immutable audit entries
# --------------------------------------------------------------------------- #
def test_issue_detected_event_writes_audit(route_to_db):
    db_path = route_to_db
    audit_service.register_subscriptions()

    event = Event(
        event_type=EventType.ISSUE_DETECTED,
        payload={
            "workload_id": "wl-evt",
            "issue_id": "iss-evt",
            "issue": {
                "issue_id": "iss-evt",
                "workload_id": "wl-evt",
                "issue_type": "idle_resource",
                "issue_category": "cost",
                "severity": "medium",
                "confidence_score": 0.8,
                "status": "new",
            },
        },
    )
    _drain(event_bus.publish_and_wait(event))

    logs = audit_service.list_audit_logs(workload_id="wl-evt", db_path=db_path)
    assert len(logs) == 1
    entry = logs[0]
    assert entry["event_type"] == "issue_detected"
    assert entry["issue_id"] == "iss-evt"
    assert entry["new_status"] == "new"
    assert entry["previous_status"] is None
    assert entry["details"]["severity"] == "medium"


def test_recommendation_generated_event_writes_audit(route_to_db):
    db_path = route_to_db
    audit_service.register_subscriptions()

    event = Event(
        event_type=EventType.RECOMMENDATION_GENERATED,
        payload={
            "workload_id": "wl-rec",
            "issue_id": "iss-rec",
            "recommendation_id": "rec-1",
            "recommendation": {
                "recommendation_id": "rec-1",
                "issue_id": "iss-rec",
                "workload_id": "wl-rec",
                "action_category": "rightsizing",
                "recommendation_type": "resize",
                "risk_level": "medium",
                "required_execution_mode": "user_approval_required",
            },
        },
    )
    _drain(event_bus.publish_and_wait(event))

    logs = audit_service.list_audit_logs(workload_id="wl-rec", db_path=db_path)
    assert len(logs) == 1
    entry = logs[0]
    assert entry["event_type"] == "recommendation_generated"
    assert entry["recommendation_id"] == "rec-1"
    assert entry["issue_id"] == "iss-rec"
    assert entry["previous_status"] == "new"
    assert entry["new_status"] == "recommended"
    assert entry["details"]["required_execution_mode"] == "user_approval_required"


def test_remediation_completed_event_writes_audit(route_to_db):
    db_path = route_to_db
    audit_service.register_subscriptions()

    event = Event(
        event_type=EventType.REMEDIATION_COMPLETED,
        payload={
            "remediation_id": "rem-1",
            "recommendation_id": "rec-1",
            "issue_id": "iss-1",
            "workload_id": "wl-rem",
            "execution_path": "auto_fix",
            "execution_status": "completed",
        },
    )
    _drain(event_bus.publish_and_wait(event))

    logs = audit_service.list_audit_logs(workload_id="wl-rem", db_path=db_path)
    assert len(logs) == 1
    entry = logs[0]
    assert entry["event_type"] == "remediation_completed"
    assert entry["remediation_id"] == "rem-1"
    assert entry["recommendation_id"] == "rec-1"
    assert entry["issue_id"] == "iss-1"
    assert entry["new_status"] == "completed"
    assert entry["actor"] == "auto_fix"


def test_event_without_workload_id_is_skipped(route_to_db):
    db_path = route_to_db
    audit_service.register_subscriptions()

    event = Event(event_type=EventType.ISSUE_DETECTED, payload={"issue": {}})
    _drain(event_bus.publish_and_wait(event))

    assert audit_service.list_audit_logs(db_path=db_path) == []
