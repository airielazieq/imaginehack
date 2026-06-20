"""Alert delivery, retry, and auto-resolution (task 16.2).

Implements the delivery + lifecycle half of the Alert System (design "Alert
System", Requirements 13.2 / 13.4):

**Delivery (Requirement 13.2).** When the alert engine fires ``ALERT_FIRED``,
the alert is delivered through the simulated
:class:`~backend.connectors.notification_connector.NotificationConnector`.
Critical alerts escalate straight to an on-call operator; lower severities
notify the workload owner team. Delivery is retried up to
:data:`MAX_DELIVERY_ATTEMPTS` times; if every attempt fails the alert is marked
``delivery_failed`` (still an "open" status — see
:data:`backend.services.alert_service.ACTIVE_STATUSES`). On success the alert
stays ``active`` and records ``delivered_at`` / ``delivery_attempts``.

The notification connector is *simulated* and always succeeds, so the retry /
``delivery_failed`` path is reached only when a connector tool raises (e.g. an
injected failure in tests or a future real connector outage). Retries are
spaced by :data:`RETRY_INTERVAL_SECONDS` (design: 3× at 10s); the sleep is
injectable and defaults to a no-op so the simulated path stays fast.

**Auto-resolution (Requirement 13.4).** When the underlying condition clears
the workload's open alert is resolved (``status="resolved"``, ``resolved_at``,
``resolution_method``). Two triggers are wired:

- ``REMEDIATION_COMPLETED`` — a remediation finished for the workload, so the
  open alert is resolved with method ``remediation_completed``.
- ``SCORE_UPDATED`` with a healthy score (at/below the engine's generation
  threshold) — the Priority Score has returned to the healthy band, so the
  open alert is resolved with method ``condition_cleared``.

:func:`register_subscriptions` (idempotent) wires all three handlers and is
called from the application lifespan alongside the alert engine.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from backend.connectors.notification_connector import NotificationConnector
from backend.core.event_bus import Event, EventType, event_bus
from backend.modules.alerts.alert_engine import MIN_ALERT_SCORE
from backend.schemas.alert import Alert
from backend.services import alert_service

logger = logging.getLogger("clover.alerts.delivery")

# Delivery retry policy (design "Alert System": retry 3× at 10s intervals).
MAX_DELIVERY_ATTEMPTS = 3
RETRY_INTERVAL_SECONDS = 10.0

# Per-severity delivery SLA targets, in seconds (design "Alert System" /
# Requirement 13.2): critical alerts must be delivered within 30s, all
# non-critical severities within 5 minutes. Delivery is SLA-compliant when
# ``delivered_at - first_attempt_at <= DELIVERY_SLA_SECONDS[severity]``.
CRITICAL_SLA_SECONDS = 30.0
NON_CRITICAL_SLA_SECONDS = 300.0
DELIVERY_SLA_SECONDS: dict[str, float] = {
    "critical": CRITICAL_SLA_SECONDS,
    "high": NON_CRITICAL_SLA_SECONDS,
    "medium": NON_CRITICAL_SLA_SECONDS,
    "low": NON_CRITICAL_SLA_SECONDS,
}

# Tool used to escalate delivery to an on-call operator when the SLA window is
# breached or owner delivery keeps failing.
_OPERATOR_TOOL = "escalate_to_operator"

# Default connector instance (simulated). Overridable per-call for tests.
_connector = NotificationConnector()

# Sleep hook between retries; default no-op keeps the simulated path instant.
SleepFn = Callable[[float], Awaitable[None]]

# Clock hook; injectable so tests can simulate the passage of time and exercise
# the SLA-breach escalation path without real sleeps.
ClockFn = Callable[[], datetime]


async def _no_sleep(_seconds: float) -> None:
    return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sla_for_severity(severity: str) -> float:
    """Return the delivery SLA target (seconds) for a severity.

    Critical alerts use the tight 30s window; every other severity uses the
    5-minute non-critical window (design "Alert System" / Requirement 13.2).
    Unknown severities fall back to the non-critical window.
    """
    return DELIVERY_SLA_SECONDS.get(severity, NON_CRITICAL_SLA_SECONDS)


def _primary_tool(alert: Alert) -> str:
    """The notification tool used for the alert's *first* delivery attempt.

    Critical alerts escalate straight to an on-call operator; lower severities
    notify the workload owner team.
    """
    return _OPERATOR_TOOL if alert.severity == "critical" else "notify_owner"


def _deliver_once(
    alert: Alert,
    connector: NotificationConnector,
    *,
    tool: str | None = None,
) -> bool:
    """Invoke a notification tool for the alert.

    By default uses the severity-appropriate primary tool
    (:func:`_primary_tool`); pass ``tool`` to force a specific channel (e.g.
    ``escalate_to_operator`` for an SLA-breach escalation).

    Returns ``True`` when the simulated delivery succeeded. The connector's
    ``execute_tool`` never raises (it returns a record with ``status="failed"``
    on error), so success is determined from that status; any exception from a
    non-standard / injected connector is also treated as a failed attempt by
    the caller.
    """
    tool = tool or _primary_tool(alert)
    message = f"[{alert.severity.upper()}] {alert.title} - {alert.recommended_action}"
    execution = connector.execute_tool(
        tool,
        workload_id=alert.workload_id,
        message=message,
    )
    return getattr(execution, "status", "success") != "failed"


def _escalate_delivery(
    alert: Alert,
    connector: NotificationConnector,
    *,
    reason: str,
    now: ClockFn,
) -> None:
    """Escalate alert delivery to an on-call operator (best-effort).

    Triggered when the SLA window is breached or owner delivery is exhausted.
    Records the escalation on the alert (``escalated`` / ``escalated_at``)
    regardless of whether the simulated operator notification itself succeeds,
    so the escalation is always auditable. For ``critical`` alerts (whose
    primary channel is already the operator) the flag still records that a
    distinct delivery escalation was raised.
    """
    if alert.escalated:
        return
    message = (
        f"[DELIVERY-ESCALATION:{reason}] {alert.severity.upper()} "
        f"{alert.title} ({alert.alert_id})"
    )
    try:
        connector.execute_tool(
            _OPERATOR_TOOL,
            workload_id=alert.workload_id,
            message=message,
        )
    except Exception:  # noqa: BLE001 - escalation is best-effort
        logger.exception(
            "Operator escalation for alert %s raised", alert.alert_id
        )
    alert.escalated = True
    alert.escalated_at = now()
    logger.warning(
        "Escalated delivery of alert %s to operator (reason=%s)",
        alert.alert_id,
        reason,
    )


async def deliver_alert(
    alert: Alert,
    *,
    connector: NotificationConnector | None = None,
    sleep: SleepFn | None = None,
    now: ClockFn | None = None,
    db_path: str | None = None,
) -> Alert:
    """Deliver an alert with retry + SLA tracking, persisting the result.

    Tries delivery up to :data:`MAX_DELIVERY_ATTEMPTS` times against the
    severity-appropriate channel. Stamps the delivery window
    (``first_attempt_at`` / ``last_attempt_at`` / ``delivered_at``) and the
    per-severity SLA target (``delivery_sla_seconds``) so SLA compliance can be
    evaluated as ``delivered_at - first_attempt_at <= delivery_sla_seconds``.

    Escalation to an on-call operator is triggered when either the SLA window
    is breached (``sla_breached``) or every delivery attempt fails (delivery is
    marked ``delivery_failed`` and escalated). On success the alert keeps its
    ``active`` status. The ``now`` clock is injectable so tests can simulate
    elapsed time without real sleeps.
    """
    connector = connector or _connector
    sleep = sleep or _no_sleep
    now = now or _utcnow

    sla = sla_for_severity(alert.severity)
    alert.delivery_sla_seconds = sla

    def _elapsed(at: datetime) -> float:
        start = alert.first_attempt_at or at
        return (at - start).total_seconds()

    def _check_sla_breach(at: datetime) -> None:
        if alert.sla_breached or alert.first_attempt_at is None:
            return
        if _elapsed(at) > sla:
            _escalate_delivery(alert, connector, reason="sla_breach", now=now)
            alert.sla_breached = True

    last_error: Exception | None = None
    for attempt in range(1, MAX_DELIVERY_ATTEMPTS + 1):
        attempt_at = now()
        alert.delivery_attempts = attempt
        if alert.first_attempt_at is None:
            alert.first_attempt_at = attempt_at
        alert.last_attempt_at = attempt_at

        delivered = False
        try:
            delivered = _deliver_once(alert, connector)
        except Exception as exc:  # noqa: BLE001 - retry on any delivery error
            last_error = exc
            delivered = False
            logger.warning(
                "Alert %s delivery attempt %d/%d raised: %s",
                alert.alert_id,
                attempt,
                MAX_DELIVERY_ATTEMPTS,
                exc,
            )

        if delivered:
            # Success: keep the alert open/active, stamp the delivery and
            # evaluate SLA compliance against the delivery time.
            delivered_at = now()
            alert.delivered_at = delivered_at
            if _elapsed(delivered_at) > sla:
                _escalate_delivery(
                    alert, connector, reason="sla_breach", now=now
                )
                alert.sla_breached = True
            if alert.status == "delivery_failed":
                alert.status = "active"
            alert_service.update_alert(alert, db_path=db_path)
            logger.info(
                "Delivered %s alert %s for workload %s (attempt %d, "
                "elapsed=%.1fs, sla=%.0fs, breached=%s)",
                alert.severity,
                alert.alert_id,
                alert.workload_id,
                attempt,
                _elapsed(delivered_at),
                sla,
                alert.sla_breached,
            )
            return alert

        logger.warning(
            "Alert %s delivery attempt %d/%d failed",
            alert.alert_id,
            attempt,
            MAX_DELIVERY_ATTEMPTS,
        )
        # A failing attempt may already have blown the SLA window; escalate
        # mid-flight rather than waiting for exhaustion.
        _check_sla_breach(now())
        if attempt < MAX_DELIVERY_ATTEMPTS:
            await sleep(RETRY_INTERVAL_SECONDS)
            _check_sla_breach(now())

    # All attempts failed: mark delivery_failed and escalate to an operator.
    alert.status = "delivery_failed"
    _escalate_delivery(alert, connector, reason="delivery_exhausted", now=now)
    alert_service.update_alert(alert, db_path=db_path)
    logger.error(
        "Alert %s delivery failed after %d attempts (last error: %s)",
        alert.alert_id,
        MAX_DELIVERY_ATTEMPTS,
        last_error,
    )
    return alert


def resolve_active_alert(
    workload_id: str,
    *,
    method: str,
    db_path: str | None = None,
) -> Alert | None:
    """Resolve the workload's open alert, if any (Requirement 13.4).

    Sets ``status="resolved"``, ``resolved_at`` and ``resolution_method`` on the
    most recent still-open alert for the workload. Returns the resolved
    :class:`Alert`, or ``None`` when there is no open alert.
    """
    existing = alert_service.get_active_alert(workload_id, db_path=db_path)
    if existing is None:
        return None
    alert = Alert.model_validate(existing)
    alert.status = "resolved"
    alert.resolved_at = _utcnow()
    alert.resolution_method = method
    alert_service.update_alert(alert, db_path=db_path)
    logger.info(
        "Auto-resolved alert %s for workload %s (method=%s)",
        alert.alert_id,
        workload_id,
        method,
    )
    return alert


# --------------------------------------------------------------------------- #
# Event subscribers
# --------------------------------------------------------------------------- #
async def _on_alert_fired(event: Event) -> None:
    """Deliver an alert when the engine fires ``ALERT_FIRED``."""
    payload = event.payload or {}
    alert_doc = payload.get("alert")
    if not alert_doc:
        return
    try:
        alert = Alert.model_validate(alert_doc)
        await deliver_alert(alert)
    except Exception:  # noqa: BLE001 - isolate the subscriber from the bus
        logger.exception(
            "Failed to deliver alert %s", payload.get("alert_id")
        )


async def _on_remediation_completed(event: Event) -> None:
    """Auto-resolve a workload's open alert once a remediation completes."""
    payload = event.payload or {}
    workload_id = payload.get("workload_id")
    if not workload_id:
        return
    try:
        resolve_active_alert(workload_id, method="remediation_completed")
    except Exception:  # noqa: BLE001 - isolate the subscriber from the bus
        logger.exception("Failed to auto-resolve alert for %s", workload_id)


async def _on_score_updated(event: Event) -> None:
    """Auto-resolve a workload's open alert when its score returns to healthy."""
    payload = event.payload or {}
    workload_id = payload.get("workload_id")
    score = payload.get("score")
    if not workload_id or score is None:
        return
    try:
        if float(score) <= MIN_ALERT_SCORE:
            resolve_active_alert(workload_id, method="condition_cleared")
    except Exception:  # noqa: BLE001 - isolate the subscriber from the bus
        logger.exception("Failed to auto-resolve alert for %s", workload_id)


_SUBSCRIPTIONS = (
    (EventType.ALERT_FIRED, _on_alert_fired),
    (EventType.REMEDIATION_COMPLETED, _on_remediation_completed),
    (EventType.SCORE_UPDATED, _on_score_updated),
)

_subscribed = False


def register_subscriptions() -> None:
    """Wire delivery + auto-resolution to the event bus (idempotent)."""
    global _subscribed
    if _subscribed:
        return
    for event_type, handler in _SUBSCRIPTIONS:
        event_bus.subscribe(event_type, handler)
    _subscribed = True
    logger.info("Alert delivery subscribed to ALERT_FIRED / REMEDIATION_COMPLETED / SCORE_UPDATED")
