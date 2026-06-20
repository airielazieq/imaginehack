"""Tests for alert delivery SLAs + escalation (task 21.1).

Extends the delivery/retry behaviour from task 16.2 with per-severity delivery
SLAs and operator escalation (design "Alert System" / Requirement 13.2):

- **Per-severity SLA selection:** critical alerts use a 30s window, all
  non-critical severities use the 5-minute window.
- **SLA window tracking:** a delivered alert records ``delivery_sla_seconds``,
  ``first_attempt_at`` / ``last_attempt_at`` and ``delivered_at`` so compliance
  can be evaluated as ``delivered_at - first_attempt_at <= delivery_sla_seconds``.
- **Retry-then-success:** a connector that fails transiently then recovers is
  retried up to the max attempts and ends up ``active`` / delivered.
- **Retry exhaustion:** a connector that always fails leaves the alert
  ``delivery_failed`` *and* escalated to an on-call operator.
- **SLA-breach escalation:** when delivery takes longer than the severity's SLA
  window (simulated via an injectable clock) the alert is marked
  ``sla_breached`` and escalated.

Retries use the injectable no-op sleep and an injectable clock, so no test
sleeps for real. Regular pytest tests (no Hypothesis).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# --- Configure an isolated temp DB BEFORE importing config/services ----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_alert_sla_test_")
os.environ["CLOVER_DB_PATH"] = os.path.join(_TMP_DIR, "test_clover.db")

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from backend.connectors.notification_connector import NotificationConnector  # noqa: E402
from backend.core.database import init_db  # noqa: E402
from backend.modules.alerts import alert_engine, delivery  # noqa: E402
from backend.schemas.workload import Workload  # noqa: E402
from backend.services import alert_service, workload_service  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db_path(tmp_path) -> str:
    path = str(tmp_path / "alerts_sla_test.db")
    init_db(path)
    return path


def _seed_workload(db_path: str | None, workload_id: str = "wl-sla") -> str:
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


class _AlwaysFailingConnector(NotificationConnector):
    """Every delivery tool reports a simulated failure."""

    def _tool_notify_owner(self, **params):  # type: ignore[override]
        return {"status": "failed", "message": "simulated outage"}

    def _tool_escalate_to_operator(self, **params):  # type: ignore[override]
        return {"status": "failed", "message": "simulated outage"}


class _FlakyConnector(NotificationConnector):
    """Fails the first ``fail_times`` delivery calls, then recovers."""

    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self._remaining = fail_times
        self.escalations = 0

    def _tool_notify_owner(self, **params):  # type: ignore[override]
        if self._remaining > 0:
            self._remaining -= 1
            return {"status": "failed", "message": "transient"}
        return super()._tool_notify_owner(**params)

    def _tool_escalate_to_operator(self, **params):  # type: ignore[override]
        self.escalations += 1
        return super()._tool_escalate_to_operator(**params)


class _CountingConnector(NotificationConnector):
    """Succeeds on every call but records operator escalations."""

    def __init__(self) -> None:
        super().__init__()
        self.escalations = 0

    def _tool_escalate_to_operator(self, **params):  # type: ignore[override]
        self.escalations += 1
        return super()._tool_escalate_to_operator(**params)


class _FakeClock:
    """Monotonic clock that advances a fixed step on every call."""

    def __init__(self, start: datetime, step_seconds: float) -> None:
        self._t = start
        self._step = timedelta(seconds=step_seconds)

    def __call__(self) -> datetime:
        current = self._t
        self._t = self._t + self._step
        return current


def _new_alert(db_path: str, workload_id: str, score: float):
    alert = alert_engine.build_alert(workload_id, score, db_path=db_path)
    assert alert is not None
    alert_service.create_alert(alert, db_path=db_path)
    return alert


# --------------------------------------------------------------------------- #
# Per-severity SLA selection (Requirement 13.2)
# --------------------------------------------------------------------------- #
def test_sla_for_severity_selects_per_severity_target():
    assert delivery.sla_for_severity("critical") == delivery.CRITICAL_SLA_SECONDS
    assert delivery.CRITICAL_SLA_SECONDS == 30.0
    for severity in ("high", "medium", "low"):
        assert delivery.sla_for_severity(severity) == delivery.NON_CRITICAL_SLA_SECONDS
    assert delivery.NON_CRITICAL_SLA_SECONDS == 300.0
    # Unknown severities fall back to the non-critical window.
    assert delivery.sla_for_severity("unknown") == delivery.NON_CRITICAL_SLA_SECONDS


def test_delivery_records_sla_window_within_target(db_path):
    _seed_workload(db_path, "wl-win")
    alert = _new_alert(db_path, "wl-win", 90.0)  # critical
    assert alert.severity == "critical"

    delivered = _drain(delivery.deliver_alert(alert, db_path=db_path))

    assert delivered.status == "active"
    assert delivered.delivery_sla_seconds == delivery.CRITICAL_SLA_SECONDS
    assert delivered.first_attempt_at is not None
    assert delivered.last_attempt_at is not None
    assert delivered.delivered_at is not None
    # Real-clock delivery is effectively instant: within SLA, no escalation.
    assert delivered.sla_breached is False
    assert delivered.escalated is False

    stored = alert_service.get_alert(alert.alert_id, db_path=db_path)
    assert stored["delivery_sla_seconds"] == delivery.CRITICAL_SLA_SECONDS
    assert stored["sla_breached"] is False


# --------------------------------------------------------------------------- #
# Retry-then-success (Requirement 13.2)
# --------------------------------------------------------------------------- #
def test_retry_then_success_keeps_alert_active(db_path):
    _seed_workload(db_path, "wl-flaky")
    alert = _new_alert(db_path, "wl-flaky", 70.0)  # high -> notify_owner
    assert alert.severity == "high"

    connector = _FlakyConnector(fail_times=2)
    delivered = _drain(
        delivery.deliver_alert(alert, connector=connector, db_path=db_path)
    )

    # Two transient failures then success on the third attempt.
    assert delivered.status == "active"
    assert delivered.delivery_attempts == 3
    assert delivered.delivered_at is not None
    # Fast (no-op sleep) delivery stays within the 5-minute window.
    assert delivered.sla_breached is False
    assert delivered.escalated is False
    assert connector.escalations == 0

    stored = alert_service.get_alert(alert.alert_id, db_path=db_path)
    assert stored["status"] == "active"


# --------------------------------------------------------------------------- #
# Retry exhaustion -> delivery_failed + escalation (Requirement 13.2)
# --------------------------------------------------------------------------- #
def test_retry_exhaustion_marks_failed_and_escalates(db_path):
    _seed_workload(db_path, "wl-dead")
    alert = _new_alert(db_path, "wl-dead", 70.0)  # high -> notify_owner

    delivered = _drain(
        delivery.deliver_alert(
            alert, connector=_AlwaysFailingConnector(), db_path=db_path
        )
    )

    assert delivered.status == "delivery_failed"
    assert delivered.delivery_attempts == delivery.MAX_DELIVERY_ATTEMPTS
    # Exhausted owner delivery is escalated to an on-call operator.
    assert delivered.escalated is True
    assert delivered.escalated_at is not None

    stored = alert_service.get_alert(alert.alert_id, db_path=db_path)
    assert stored["status"] == "delivery_failed"
    assert stored["escalated"] is True
    # delivery_failed is still an open status.
    assert alert_service.get_active_alert("wl-dead", db_path=db_path) is not None


# --------------------------------------------------------------------------- #
# SLA-breach escalation (Requirement 13.2)
# --------------------------------------------------------------------------- #
def test_sla_breach_escalates_on_slow_delivery(db_path):
    _seed_workload(db_path, "wl-slow")
    alert = _new_alert(db_path, "wl-slow", 90.0)  # critical, 30s SLA

    # Clock jumps 60s per call: the success arrives well past the 30s window.
    clock = _FakeClock(datetime(2024, 1, 1, tzinfo=timezone.utc), step_seconds=60.0)
    connector = _CountingConnector()

    delivered = _drain(
        delivery.deliver_alert(
            alert, connector=connector, now=clock, db_path=db_path
        )
    )

    assert delivered.status == "active"  # it WAS delivered, just late
    assert delivered.delivered_at is not None
    assert delivered.sla_breached is True
    assert delivered.escalated is True
    assert delivered.escalated_at is not None
    # The operator escalation actually fired through the connector.
    assert connector.escalations >= 1

    stored = alert_service.get_alert(alert.alert_id, db_path=db_path)
    assert stored["sla_breached"] is True
    assert stored["escalated"] is True


def test_non_critical_within_five_minutes_not_breached(db_path):
    _seed_workload(db_path, "wl-medium")
    alert = _new_alert(db_path, "wl-medium", 50.0)  # medium -> 300s SLA
    assert alert.severity == "medium"

    # 60s elapsed is comfortably inside the 5-minute non-critical window.
    clock = _FakeClock(datetime(2024, 1, 1, tzinfo=timezone.utc), step_seconds=60.0)
    delivered = _drain(delivery.deliver_alert(alert, now=clock, db_path=db_path))

    assert delivered.status == "active"
    assert delivered.sla_breached is False
    assert delivered.escalated is False
