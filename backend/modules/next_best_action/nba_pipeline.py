"""NBA pipeline wiring for Module 2 (task 4.4).

Composes the Module 2 components built in tasks 4.1-4.3 into a single
end-to-end pipeline and wires it to the event bus:

    Issue (+ Workload + latest telemetry)
      -> rule match + risk/execution mode      (nba_engine.build_draft)
      -> XGBoost 30-day forecast               (xgboost_forecast.forecast_snapshot)
      -> Optimization Impact Forecast          (optimization_impact.compute_*)
      -> assembled Recommendation              (nba_engine.assemble_recommendation)
      -> persist (recommendation_service)
      -> emit RECOMMENDATION_GENERATED

Two entry points share the same synchronous core
(:func:`build_recommendation`):

- The **event-driven** path: :func:`register_subscriptions` subscribes
  :func:`_on_issue_detected` to ``ISSUE_DETECTED`` so the
  telemetry -> detection -> recommendation flow runs end to end. The handler is
  idempotent per issue (a re-detected/consolidated issue does not produce a
  duplicate recommendation) and subscription registration is idempotent.

- The **API-driven** path: :func:`generate_for_issue_id` powers
  ``POST /api/recommendations/generate/{issueId}`` (generate-on-demand).

Both persist the Recommendation and emit ``RECOMMENDATION_GENERATED``.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.core.event_bus import Event, EventType, event_bus
from backend.modules.next_best_action import nba_engine
from backend.modules.next_best_action.optimization_impact import (
    compute_optimization_impact,
)
from backend.modules.next_best_action.xgboost_forecast import forecast_snapshot
from backend.modules.self_healing.approval_queue import approval_queue
from backend.schemas.recommendation import Recommendation
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload
from backend.services import (
    issue_service,
    recommendation_service,
    telemetry_service,
    workload_service,
)

logger = logging.getLogger("clover.nba.pipeline")


# --------------------------------------------------------------------------- #
# Context resolution
# --------------------------------------------------------------------------- #
def _resolve_workload(workload_id: str, *, db_path: str | None = None) -> Workload | None:
    """Look up and coerce a :class:`Workload` for the NBA context (or None)."""
    raw = workload_service.get_workload(workload_id, db_path=db_path)
    if raw is None:
        return None
    try:
        return Workload(**raw)
    except Exception:  # noqa: BLE001 - malformed workload context is non-fatal
        logger.warning("Could not build Workload for %s; proceeding without it", workload_id)
        return None


def _latest_telemetry(workload_id: str, *, db_path: str | None = None) -> TelemetrySnapshot | None:
    """Return the most recent :class:`TelemetrySnapshot` for a workload, or None."""
    history = telemetry_service.get_telemetry_history(
        workload_id, limit=1, db_path=db_path
    )
    if not history:
        return None
    try:
        return TelemetrySnapshot(**history[0])
    except Exception:  # noqa: BLE001
        logger.exception("Latest telemetry for %s is invalid", workload_id)
        return None


# --------------------------------------------------------------------------- #
# Synchronous core: Issue -> full Recommendation (no persistence / no events)
# --------------------------------------------------------------------------- #
def build_recommendation(
    issue: Any,
    *,
    workload: Workload | None = None,
    telemetry: TelemetrySnapshot | None = None,
    db_path: str | None = None,
) -> Recommendation | None:
    """Compose a full :class:`Recommendation` for an Issue.

    Runs the deterministic draft (rule match + risk/mode), the XGBoost forecast
    (task 4.2) and the optimization-impact calculator (task 4.3), then assembles
    the Recommendation. Returns ``None`` when no recommendation rule covers the
    issue type.

    Args:
        issue: An :class:`~backend.schemas.issue.Issue` (or any object exposing
            ``issue_type`` / ``issue_category`` / ``workload_id`` /
            ``detected_evidence`` / ``severity``). The NBA engine accepts the
            model; callers usually pass a parsed ``Issue``.
        workload: Resolved workload context (looked up if omitted).
        telemetry: Latest telemetry snapshot (looked up if omitted). Required to
            produce a forecast.
        db_path: Optional DB path override (tests).
    """
    workload_id = getattr(issue, "workload_id", None)
    if workload is None and workload_id:
        workload = _resolve_workload(workload_id, db_path=db_path)
    if telemetry is None and workload_id:
        telemetry = _latest_telemetry(workload_id, db_path=db_path)

    draft = nba_engine.build_draft(issue, workload, telemetry=telemetry)
    if draft is None:
        logger.info(
            "No recommendation rule matched issue %s (%s)",
            getattr(issue, "issue_id", "?"),
            getattr(issue, "issue_type", "?"),
        )
        return None

    if telemetry is None:
        logger.warning(
            "No telemetry available for workload %s; cannot forecast recommendation",
            workload_id,
        )
        return None

    # Task 4.2: baseline 30-day forecast (XGBoost, or deterministic fallback).
    forecast = forecast_snapshot(telemetry, workload)

    # Task 4.3: before / after / savings using the rule's recommendation type.
    impact = compute_optimization_impact(
        cost_30d=forecast.predicted_cost_30d,
        energy_kwh_30d=forecast.predicted_energy_kwh_30d,
        carbon_kgco2e_30d=forecast.predicted_carbon_kgco2e_30d,
        recommendation_type=draft.recommendation_type,
    )

    return nba_engine.assemble_recommendation(
        draft,
        forecast_model_result=forecast,
        optimization_impact_forecast=impact,
    )


# --------------------------------------------------------------------------- #
# Persist + emit
# --------------------------------------------------------------------------- #
async def _emit_recommendation_generated(
    recommendation: Recommendation, *, correlation_id: str | None = None
) -> None:
    """Publish ``RECOMMENDATION_GENERATED`` for a freshly produced recommendation."""
    event = Event(
        event_type=EventType.RECOMMENDATION_GENERATED,
        payload={
            "workload_id": recommendation.workload_id,
            "issue_id": recommendation.issue_id,
            "recommendation_id": recommendation.recommendation_id,
            "recommendation": recommendation.model_dump(mode="json"),
        },
    )
    if correlation_id:
        event.correlation_id = correlation_id
    await event_bus.publish(event)


def _queue_for_approval(
    recommendation: Recommendation,
    *,
    workload: Workload | None = None,
    db_path: str | None = None,
) -> None:
    """Add a recommendation that needs sign-off to the global approval queue.

    Recommendations whose ``required_execution_mode`` is
    ``user_approval_required`` must be approved by a human before the
    remediation ``execute`` endpoint will run them. Enqueueing here is what makes
    that gate real: without an item in the queue there is nothing for an operator
    to approve and nothing for the executor to check against. Best-effort — a
    queueing failure must never block recommendation generation.
    """
    if recommendation.required_execution_mode != "user_approval_required":
        return
    # Don't re-add (and thereby reset to "pending") an item that is already in
    # the queue — that would clobber an in-flight approve/deny/snooze decision.
    if approval_queue.get(recommendation.recommendation_id) is not None:
        return
    try:
        environment = workload.environment if workload is not None else None
        if environment is None:
            raw = workload_service.get_workload(
                recommendation.workload_id, db_path=db_path
            )
            environment = (raw or {}).get("environment")
        approval_queue.add(recommendation, environment=environment)
    except Exception:  # noqa: BLE001 - queueing must never break generation
        logger.exception(
            "Failed to queue recommendation %s for approval",
            recommendation.recommendation_id,
        )


def _advance_issue_status(
    recommendation: Recommendation, *, db_path: str | None = None
) -> None:
    """Move the originating issue into the remediation lifecycle.

    Once a recommendation exists, the issue is no longer just ``new``: it is
    ``pending_approval`` when the action needs human sign-off, otherwise
    ``recommended``. This write-back is what lets the UI (workload Self-Healing
    tab, issue status badges) reflect that an action is in flight. Best-effort —
    a status update must never break recommendation generation.
    """
    new_status = (
        "pending_approval"
        if recommendation.required_execution_mode == "user_approval_required"
        else "recommended"
    )
    try:
        issue_service.update_status(
            recommendation.issue_id, new_status, db_path=db_path
        )
    except Exception:  # noqa: BLE001 - status write-back is best-effort
        logger.exception(
            "Failed to advance issue %s to %s",
            recommendation.issue_id,
            new_status,
        )


async def generate_and_store(
    issue: Any,
    *,
    workload: Workload | None = None,
    telemetry: TelemetrySnapshot | None = None,
    correlation_id: str | None = None,
    db_path: str | None = None,
) -> Recommendation | None:
    """Build, persist, and announce a Recommendation for an Issue.

    Returns the persisted :class:`Recommendation`, or ``None`` when no rule
    matched the issue type (or no telemetry was available to forecast).
    """
    recommendation = build_recommendation(
        issue, workload=workload, telemetry=telemetry, db_path=db_path
    )
    if recommendation is None:
        return None
    recommendation_service.create_recommendation(recommendation, db_path=db_path)
    _queue_for_approval(recommendation, workload=workload, db_path=db_path)
    _advance_issue_status(recommendation, db_path=db_path)
    await _emit_recommendation_generated(recommendation, correlation_id=correlation_id)
    return recommendation


async def generate_for_issue_id(
    issue_id: str, *, db_path: str | None = None
) -> Recommendation | None:
    """Build, persist, and announce a recommendation for a stored issue id.

    Powers the generate-on-demand API. Returns the persisted
    :class:`Recommendation`, or ``None`` when the issue does not exist, no rule
    matched, or no telemetry was available. The API handler distinguishes the
    "issue not found" case by checking :func:`issue_exists` first.
    """
    raw_issue = issue_service.get_issue(issue_id, db_path=db_path)
    if raw_issue is None:
        return None

    # Idempotency: if a recommendation already exists for this issue, return it
    # instead of generating a duplicate. The IssueDetail page calls this endpoint
    # every time it loads (and on each "Review in approval queue" click); without
    # this guard each visit would persist a new recommendation id and enqueue a
    # duplicate approval item. Mirrors the event-driven path's idempotency check.
    existing = recommendation_service.get_latest_for_issue(issue_id, db_path=db_path)
    if existing is not None:
        try:
            return Recommendation(**existing)
        except Exception:  # noqa: BLE001 - tolerate schema drift on stored docs
            logger.warning(
                "Stored recommendation for issue %s did not validate; regenerating",
                issue_id,
            )

    issue = _parse_issue(raw_issue)
    return await generate_and_store(issue, db_path=db_path)


def _parse_issue(raw_issue: dict):
    """Parse a stored issue dict into an :class:`Issue` model.

    Falls back to a lightweight attribute shim if the stored document predates
    the current schema, so recommendation generation never hard-fails on an
    older issue record.
    """
    from backend.schemas.issue import Issue

    try:
        return Issue(**raw_issue)
    except Exception:  # noqa: BLE001 - tolerate schema drift on stored issues
        logger.warning("Stored issue %s did not validate; using a shim", raw_issue.get("issue_id"))
        return _IssueShim(raw_issue)


class _IssueShim:
    """Minimal attribute view over a raw issue dict for the NBA engine."""

    def __init__(self, raw: dict) -> None:
        self.issue_id = raw.get("issue_id", "")
        self.workload_id = raw.get("workload_id", "")
        self.issue_type = raw.get("issue_type", "")
        self.issue_category = raw.get("issue_category", "")
        self.severity = raw.get("severity", "low")
        self.detected_evidence = raw.get("detected_evidence", {})


# --------------------------------------------------------------------------- #
# Event subscription (idempotent)
# --------------------------------------------------------------------------- #
async def _on_issue_detected(event: Event) -> None:
    """Event handler: produce a Recommendation for a newly detected Issue.

    Idempotent per issue: if a recommendation already exists for the issue
    (e.g. the issue was consolidated and re-emitted), no duplicate is created.
    """
    payload = event.payload or {}
    raw_issue = payload.get("issue")
    issue_id = payload.get("issue_id") or (raw_issue or {}).get("issue_id")
    if raw_issue is None or not issue_id:
        return

    # Idempotency: skip if this issue already has a recommendation.
    if recommendation_service.get_latest_for_issue(issue_id) is not None:
        logger.debug("Issue %s already has a recommendation; skipping", issue_id)
        return

    issue = _parse_issue(raw_issue)
    try:
        await generate_and_store(issue, correlation_id=event.correlation_id)
    except Exception:  # noqa: BLE001 - isolate the subscriber from the bus
        logger.exception("Failed to generate recommendation for issue %s", issue_id)


_subscribed = False


def register_subscriptions() -> None:
    """Subscribe the NBA pipeline to ``ISSUE_DETECTED`` (idempotent)."""
    global _subscribed
    if _subscribed:
        return
    event_bus.subscribe(EventType.ISSUE_DETECTED, _on_issue_detected)
    _subscribed = True
    logger.info("NBA pipeline subscribed to ISSUE_DETECTED")
