"""Alert engine: threshold-based alert generation (task 16.1).

The alert engine is the generation half of the cross-cutting Alert System. It
listens for ``SCORE_UPDATED`` events on the event bus and, when a workload's
Priority Score crosses into actionable territory, generates an
:class:`~backend.schemas.alert.Alert`, persists it, and publishes an
``ALERT_FIRED`` event for downstream consumers (delivery, WebSocket push).

**Score-to-severity mapping** (design "Alert System", Requirement 13.1)::

    score > 80           -> critical
    60 < score <= 80     -> high
    30 < score <= 60     -> medium
    score <= 30          -> low

An alert is generated only when the Priority Score **exceeds the generation
threshold** (:data:`MIN_ALERT_SCORE`, default ``30.0`` — i.e. the workload has
left the healthy/low band). The alert's ``severity`` is then derived from the
score via :func:`severity_from_score` (Requirement 13.1: "generate an alert with
severity derived from the Priority_Score").

The generated alert is enriched, best-effort, from the workload's latest
persisted state:

- ``construction_workflow`` from the workload record,
- ``security_impact`` / ``energy_impact`` / ``cost_impact`` qualitative strings
  derived from the Priority Score's contributing factors,
- ``recommended_action`` from the latest Recommendation (falling back to the
  latest Issue, then a generic message),
- ``self_healing_eligible`` true when the latest Recommendation can be applied
  automatically (``required_execution_mode == "auto_fix"``).

Suppression / deduplication and delivery / auto-resolve are intentionally
**deferred to task 16.2**; this module only generates and persists alerts and
fires the ``ALERT_FIRED`` event.

:func:`register_subscriptions` (idempotent) wires the engine to
``SCORE_UPDATED`` and is called from the application lifespan, mirroring the
pattern used by the detector / NBA pipeline / scorer / audit recorder.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.core.event_bus import Event, EventType, event_bus
from backend.modules.alerts import suppression
from backend.schemas.alert import Alert, Severity
from backend.services import (
    alert_service,
    issue_service,
    recommendation_service,
    workload_service,
)

logger = logging.getLogger("clover.alerts.engine")

# Minimum Priority Score for an alert to be generated. Scores at or below this
# threshold are in the healthy/low band and do not raise an alert.
MIN_ALERT_SCORE = 30.0

# Score band upper bounds for the severity mapping (design "Alert System").
_CRITICAL_THRESHOLD = 80.0
_HIGH_THRESHOLD = 60.0
_MEDIUM_THRESHOLD = 30.0

_MAX_TITLE = 120
_MAX_IMPACT = 500


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def severity_from_score(score: float) -> Severity:
    """Map a Priority Score (0-100) to an alert severity.

    ``> 80 -> critical``, ``60-80 -> high``, ``30-60 -> medium``,
    ``<= 30 -> low`` (design "Alert System" / Requirement 13.1).
    """
    if score > _CRITICAL_THRESHOLD:
        return "critical"
    if score > _HIGH_THRESHOLD:
        return "high"
    if score > _MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def _factor_phrase(value: Optional[float], subject: str) -> str:
    """Render a contributing-factor value (0-1) as a short qualitative string."""
    if value is None:
        return f"{subject}: no data available."
    if value >= 0.75:
        level = "critical"
    elif value >= 0.5:
        level = "elevated"
    elif value >= 0.25:
        level = "moderate"
    else:
        level = "low"
    return f"{subject}: {level} ({round(value * 100)}%)."


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def build_alert(
    workload_id: str,
    score: float,
    *,
    priority_score: dict | None = None,
    db_path: str | None = None,
) -> Optional[Alert]:
    """Build an :class:`Alert` for a workload from its score + latest state.

    Returns ``None`` when ``score`` does not exceed :data:`MIN_ALERT_SCORE`
    (no alert-worthy condition). Otherwise builds a fully-populated, validated
    :class:`Alert` in ``active`` status. Does not persist or emit anything.
    """
    if score <= MIN_ALERT_SCORE:
        return None

    severity = severity_from_score(score)
    factors = priority_score or {}

    workload = workload_service.get_workload(workload_id, db_path=db_path)
    workload_name = (
        workload.get("workload_name", workload_id) if workload else workload_id
    )
    construction_workflow = (
        (workload.get("construction_workflow") if workload else None) or "unknown"
    )

    recommendations = recommendation_service.list_recommendations(
        workload_id=workload_id, db_path=db_path
    )
    latest_rec = recommendations[0] if recommendations else None

    issues = issue_service.list_issues(workload_id=workload_id, db_path=db_path)
    latest_issue = issues[0] if issues else None

    self_healing_eligible = bool(
        latest_rec
        and latest_rec.get("required_execution_mode") == "auto_fix"
    )

    if latest_rec and latest_rec.get("recommendation_type"):
        recommended_action = str(latest_rec["recommendation_type"])
    elif latest_issue and latest_issue.get("issue_type"):
        recommended_action = f"Review {latest_issue['issue_type']} on {workload_name}"
    else:
        recommended_action = f"Review workload {workload_name} and remediate"

    title = _truncate(
        f"{severity.capitalize()} priority alert: {workload_name}", _MAX_TITLE
    )

    return Alert(
        alert_id=f"alert-{uuid.uuid4().hex[:12]}",
        title=title,
        workload_id=workload_id,
        construction_workflow=construction_workflow,
        severity=severity,
        security_impact=_truncate(
            _factor_phrase(factors.get("security_severity"), "Security risk"),
            _MAX_IMPACT,
        ),
        energy_impact=_truncate(
            _factor_phrase(factors.get("energy_waste"), "Energy waste"), _MAX_IMPACT
        ),
        cost_impact=_truncate(
            _factor_phrase(factors.get("cost_waste"), "Cost waste"), _MAX_IMPACT
        ),
        recommended_action=recommended_action,
        self_healing_eligible=self_healing_eligible,
        status="active",
        priority_score=round(float(score), 1),
        created_at=_utcnow(),
    )


async def generate_for_workload(
    workload_id: str,
    score: float,
    *,
    priority_score: dict | None = None,
    correlation_id: str | None = None,
    db_path: str | None = None,
) -> Optional[Alert]:
    """Generate, persist, and announce an alert for a workload.

    Builds an alert from the score (see :func:`build_alert`); if the score is
    below the generation threshold, returns ``None`` and does nothing.
    Otherwise persists the alert and publishes an ``ALERT_FIRED`` event, then
    returns the stored :class:`Alert`.
    """
    alert = build_alert(
        workload_id, score, priority_score=priority_score, db_path=db_path
    )
    if alert is None:
        logger.debug(
            "Score %.1f for %s below threshold %.1f; no alert generated",
            score,
            workload_id,
            MIN_ALERT_SCORE,
        )
        return None

    # Suppression / deduplication (task 16.2, Requirement 13.3): if the
    # workload already has an open alert within the 15-minute window, suppress
    # this duplicate (increment its counter) instead of creating a new one.
    suppressed = suppression.check_and_suppress(workload_id, db_path=db_path)
    if suppressed is not None:
        logger.debug(
            "Duplicate alert for %s suppressed (count=%s)",
            workload_id,
            suppressed.get("suppression_count"),
        )
        return None

    alert_service.create_alert(alert, db_path=db_path)

    event = Event(
        event_type=EventType.ALERT_FIRED,
        payload={
            "workload_id": workload_id,
            "alert_id": alert.alert_id,
            "severity": alert.severity,
            "priority_score": alert.priority_score,
            "alert": alert.model_dump(mode="json"),
        },
    )
    if correlation_id:
        event.correlation_id = correlation_id
    await event_bus.publish(event)
    logger.info(
        "Generated %s alert %s for workload %s (score=%.1f)",
        alert.severity,
        alert.alert_id,
        workload_id,
        alert.priority_score,
    )
    return alert


# --------------------------------------------------------------------------- #
# Event subscription (idempotent)
# --------------------------------------------------------------------------- #
async def _on_score_updated(event: Event) -> None:
    """Generate an alert when a workload's Priority Score crosses the threshold.

    Reads ``workload_id``, ``score`` and the full ``priority_score`` document
    from the ``SCORE_UPDATED`` payload emitted by the priority scorer.
    """
    payload = event.payload or {}
    workload_id = payload.get("workload_id")
    if not workload_id:
        return
    score = payload.get("score")
    if score is None:
        return
    try:
        await generate_for_workload(
            workload_id,
            float(score),
            priority_score=payload.get("priority_score"),
            correlation_id=event.correlation_id,
        )
    except Exception:  # noqa: BLE001 - isolate the subscriber from the bus
        logger.exception("Failed to generate alert for %s", workload_id)


_subscribed = False


def register_subscriptions() -> None:
    """Subscribe the alert engine to ``SCORE_UPDATED`` events.

    Idempotent: repeated calls (across test setups or re-imports) register the
    handler at most once. Called from the application lifespan.
    """
    global _subscribed
    if _subscribed:
        return
    event_bus.subscribe(EventType.SCORE_UPDATED, _on_score_updated)
    _subscribed = True
    logger.info("Alert engine subscribed to %s", EventType.SCORE_UPDATED.value)
