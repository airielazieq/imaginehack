"""Tests for alert suppression, delivery, and auto-resolution (task 16.2).

Covers the delivery + lifecycle half of the Alert System:

- **Suppression / dedup (Req 13.3):** a second alert-worthy score for the same
  workload within the 15-minute window is suppressed (no new alert, no
  ``ALERT_FIRED``) and the existing alert's ``suppression_count`` is
  incremented. A score for a *different* workload is not suppressed.
- **Delivery (Req 13.2):** a successfully delivered alert stays ``active`` with
  ``delivered_at`` stamped; an alert whose connector keeps failing is retried
  up to 3× and ends up ``delivery_failed``.
- **Auto-resolution (Req 13.4):** the workload's open alert is resolved (with
  ``resolved_at`` / ``resolution_method``) on ``REMEDIATION_COMPLETED`` and when
  the Priority Score returns to the healthy band.
- **GET /api/alerts:** lists alerts as a bare array in ``data`` and supports
  ``workload_id`` / ``severity`` filters (via TestClient).

An isolated temp SQLite DB is configured via ``CLOVER_DB_PATH`` before the app
is imported so the API tests never touch the real clover.db; the unit tests use
their own per-test temp DB via the ``db_path`` override. Regular pytest tests
(no Hypothesis).
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_alerts_api_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.connectors.notification_connector import NotificationConnector  # noqa: E402
from backend.core.database import init_db  # noqa: E402
from backend.core.event_bus import Event, EventType, event_bus  # noqa: E402
from backend.main import app  # noqa: E402
from backend.modules.alerts import alert_engine, delivery, suppression  # noqa: E402
from backend.schemas.workload import Workload  # noqa: E402
from backend.services import alert_service, workload_service  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db_path(tmp_path) -> str:
    """An initialized, isolated SQLite DB for a single unit test."""
    path = str(tmp_path / "alerts_delivery_test.db")
    init_db(path)
    return path


def _seed_workload(db_path: str | None, workload_id: str = "wl-del") -> str:
    workload = Workload(
        workload_id=workload_id,
        workload_name="Field App",
        workload_type="web_service",
        cloud_service_type="vm",
        environment="production",  # type: ignore[arg-type]
        region="us-east-1",
        owner_team="platform-team",
        construction_workflow="site_progress_tracking_system",
        workflow_criticality="high",  # type: ignore[arg-type]
        status="warning",
    )
    workload_service.upsert_workload(workload, db_path=db_path)
    return workload_id


def _drain(coro):
    return asyncio.run(coro)


class _FailingNotificationConnector(NotificationConnector):
    """Connector whose delivery tools always report a simulated failure."""

    def _tool_notify_owner(self, **params):  # type: ignore[override]
        return {"status": "failed", "message": "simulated outage"}

    def _tool_escalate_to_operator(self, **params):  # type: ignore[override]
        return {"status": "failed", "message": "simulated outage"}


# --------------------------------------------------------------------------- #
# Suppression / deduplication (Requirement 13.3)
# --------------------------------------------------------------------------- #
def test_duplicate_alert_for_same_workload_is_suppressed(db_path):
    _seed_workload(db_path, "wl-dup")
    fired: list[Event] = []

    async def _capture(event: Event) -> None:
        fired.append(event)

    async def _run():
        event_bus.subscribe(EventType.ALERT_FIRED, _capture)
        try:
            first = await alert_engine.generate_for_workload(
                "wl-dup", 90.0, db_path=db_path
            )
            second = await alert_engine.generate_for_workload(
                "wl-dup", 85.0, db_path=db_path
            )
            await asyncio.sleep(0.05)
            return first, second
        finally:
            event_bus.unsubscribe(EventType.ALERT_FIRED, _capture)

    first, second = _drain(_run())

    # First generated, second suppressed.
    assert first is not None
    assert second is None

    alerts = alert_service.list_alerts(workload_id="wl-dup", db_path=db_path)
    assert len(alerts) == 1
    # The surviving alert carries the incremented suppression counter.
    assert alerts[0]["suppression_count"] == 1
    assert alerts[0]["suppressed_until"] is not None
    # Only the first alert fired ALERT_FIRED.
    assert len(fired) == 1


def test_alerts_for_different_workloads_are_not_suppressed(db_path):
    _seed_workload(db_path, "wl-x")
    _seed_workload(db_path, "wl-y")

    async def _run():
        await alert_engine.generate_for_workload("wl-x", 90.0, db_path=db_path)
        await alert_engine.generate_for_workload("wl-y", 70.0, db_path=db_path)

    _drain(_run())

    assert len(alert_service.list_alerts(db_path=db_path)) == 2


def test_suppression_skipped_outside_window(db_path):
    _seed_workload(db_path, "wl-old")

    async def _seed():
        await alert_engine.generate_for_workload("wl-old", 90.0, db_path=db_path)

    _drain(_seed())

    existing = alert_service.get_active_alert("wl-old", db_path=db_path)
    assert existing is not None
    # An alert created well outside the 15-minute window is not in-window.
    existing["created_at"] = "2000-01-01T00:00:00+00:00"
    existing["suppressed_until"] = None
    assert suppression.is_within_window(existing) is False


# --------------------------------------------------------------------------- #
# Delivery (Requirement 13.2)
# --------------------------------------------------------------------------- #
def test_delivery_success_keeps_alert_active_and_stamps_delivered(db_path):
    _seed_workload(db_path, "wl-ok")
    alert = alert_engine.build_alert("wl-ok", 90.0, db_path=db_path)
    assert alert is not None
    alert_service.create_alert(alert, db_path=db_path)

    delivered = _drain(delivery.deliver_alert(alert, db_path=db_path))

    assert delivered.status == "active"
    assert delivered.delivered_at is not None
    assert delivered.delivery_attempts == 1

    stored = alert_service.get_alert(alert.alert_id, db_path=db_path)
    assert stored["status"] == "active"
    assert stored["delivered_at"] is not None


def test_delivery_failure_marks_delivery_failed_after_retries(db_path):
    _seed_workload(db_path, "wl-fail")
    alert = alert_engine.build_alert("wl-fail", 90.0, db_path=db_path)
    assert alert is not None
    alert_service.create_alert(alert, db_path=db_path)

    delivered = _drain(
        delivery.deliver_alert(
            alert,
            connector=_FailingNotificationConnector(),
            db_path=db_path,
        )
    )

    assert delivered.status == "delivery_failed"
    assert delivered.delivery_attempts == delivery.MAX_DELIVERY_ATTEMPTS

    stored = alert_service.get_alert(alert.alert_id, db_path=db_path)
    assert stored["status"] == "delivery_failed"
    # A delivery_failed alert is still "open" (eligible for suppression/resolve).
    assert alert_service.get_active_alert("wl-fail", db_path=db_path) is not None


# --------------------------------------------------------------------------- #
# Auto-resolution (Requirement 13.4)
# --------------------------------------------------------------------------- #
def test_resolve_active_alert_sets_resolution_fields(db_path):
    _seed_workload(db_path, "wl-res")
    _drain(alert_engine.generate_for_workload("wl-res", 90.0, db_path=db_path))

    resolved = delivery.resolve_active_alert(
        "wl-res", method="remediation_completed", db_path=db_path
    )

    assert resolved is not None
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None
    assert resolved.resolution_method == "remediation_completed"
    # No longer an open alert for the workload.
    assert alert_service.get_active_alert("wl-res", db_path=db_path) is None


def test_resolve_active_alert_noop_without_open_alert(db_path):
    _seed_workload(db_path, "wl-none")
    assert (
        delivery.resolve_active_alert(
            "wl-none", method="condition_cleared", db_path=db_path
        )
        is None
    )


def test_remediation_completed_event_auto_resolves(db_path, monkeypatch):
    _seed_workload(db_path, "wl-rem")
    _drain(alert_engine.generate_for_workload("wl-rem", 90.0, db_path=db_path))

    # The handler resolves via the default DB; route it to the isolated DB.
    real_resolve = delivery.resolve_active_alert

    def _patched(workload_id, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return real_resolve(workload_id, **kwargs)

    monkeypatch.setattr(delivery, "resolve_active_alert", _patched)

    _drain(
        delivery._on_remediation_completed(
            Event(
                event_type=EventType.REMEDIATION_COMPLETED,
                payload={"workload_id": "wl-rem", "remediation_id": "rem-1"},
            )
        )
    )

    stored = alert_service.list_alerts(workload_id="wl-rem", db_path=db_path)[0]
    assert stored["status"] == "resolved"
    assert stored["resolution_method"] == "remediation_completed"


def test_healthy_score_auto_resolves_open_alert(db_path, monkeypatch):
    _seed_workload(db_path, "wl-heal")
    _drain(alert_engine.generate_for_workload("wl-heal", 90.0, db_path=db_path))

    real_resolve = delivery.resolve_active_alert

    def _patched(workload_id, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return real_resolve(workload_id, **kwargs)

    monkeypatch.setattr(delivery, "resolve_active_alert", _patched)

    # Score back in the healthy band (<= generation threshold) -> resolved.
    _drain(
        delivery._on_score_updated(
            Event(
                event_type=EventType.SCORE_UPDATED,
                payload={"workload_id": "wl-heal", "score": 10.0},
            )
        )
    )

    stored = alert_service.list_alerts(workload_id="wl-heal", db_path=db_path)[0]
    assert stored["status"] == "resolved"
    assert stored["resolution_method"] == "condition_cleared"


# --------------------------------------------------------------------------- #
# GET /api/alerts (TestClient against the env-configured temp DB)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_get_alerts_returns_bare_list_and_filters(client):
    # Seed two workloads + alerts directly in the env (CLOVER_DB_PATH) DB.
    _seed_workload(None, "api-wl-a")
    _seed_workload(None, "api-wl-b")

    crit = alert_engine.build_alert("api-wl-a", 90.0)
    high = alert_engine.build_alert("api-wl-b", 70.0)
    assert crit is not None and high is not None
    alert_service.create_alert(crit)
    alert_service.create_alert(high)

    # Unfiltered list: bare array in data, includes both seeded alerts.
    resp = client.get("/api/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)
    ids = {a["alert_id"] for a in body["data"]}
    assert {crit.alert_id, high.alert_id} <= ids

    # Filter by workload_id.
    resp_a = client.get("/api/alerts", params={"workload_id": "api-wl-a"})
    data_a = resp_a.json()["data"]
    assert [a["alert_id"] for a in data_a] == [crit.alert_id]
    assert data_a[0]["workload_id"] == "api-wl-a"

    # Filter by severity.
    resp_high = client.get("/api/alerts", params={"severity": "high"})
    sev_high = resp_high.json()["data"]
    assert all(a["severity"] == "high" for a in sev_high)
    assert high.alert_id in {a["alert_id"] for a in sev_high}
