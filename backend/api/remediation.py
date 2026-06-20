"""Remediation API (task 5.5).

Exposes the Module 3 self-healing surface (spec 10 section 4):

- ``POST /api/remediation/evaluate/{recId}`` - run the deterministic safety
  router on a stored Recommendation and return the chosen execution path +
  :class:`SafetyDecision` rationale, **without executing** anything.
- ``POST /api/remediation/execute/{recId}``  - execute the remediation through
  its safe path (runbook + verify + rollback for auto/approved fixes; ticket +
  notifications for escalations), assemble the full
  :class:`~backend.schemas.remediation.RemediationResult`, persist it with
  traceability links, and emit ``REMEDIATION_COMPLETED``.
- ``GET  /api/remediation/{id}/report``      - fetch a previously stored
  RemediationResult.

All responses use the shared success/error envelopes. Unknown recommendation /
remediation ids return HTTP 404.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from backend.core.event_bus import Event, EventType, event_bus
from backend.modules.self_healing import report_generator
from backend.schemas.api_responses import success
from backend.services import (
    issue_service,
    recommendation_service,
    remediation_service,
    workload_service,
)

logger = logging.getLogger("clover.api.remediation")

router = APIRouter(tags=["remediation"])


def _load_recommendation(recommendation_id: str) -> dict:
    """Fetch a recommendation or raise HTTP 404."""
    recommendation = recommendation_service.get_recommendation(recommendation_id)
    if recommendation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recommendation '{recommendation_id}' not found.",
        )
    return recommendation


# --------------------------------------------------------------------------- #
# Evaluate (no execution)
# --------------------------------------------------------------------------- #
@router.post(
    "/api/remediation/evaluate/{recommendation_id}",
    status_code=status.HTTP_200_OK,
)
async def evaluate_remediation(recommendation_id: str) -> dict:
    """Decide the safe execution path for a recommendation without executing it."""
    recommendation = _load_recommendation(recommendation_id)
    workload = workload_service.get_workload(recommendation["workload_id"])
    issue = issue_service.get_issue(recommendation["issue_id"])

    decision = report_generator.evaluate(recommendation, workload, issue)

    return success(
        data={
            "recommendation_id": recommendation_id,
            "execution_path": decision.execution_path,
            "approval_required": decision.approval_required,
            "rollback_available": decision.rollback_available,
            "blocklisted": decision.blocklisted,
            "matched_conditions": decision.matched_conditions,
            "safety_decision": decision.to_safety_decision().model_dump(mode="json"),
            "evaluated_conditions": decision.evaluated_conditions,
        },
        message=f"Safety evaluation complete: {decision.execution_path}.",
    )


# --------------------------------------------------------------------------- #
# Execute (produce + persist a RemediationResult)
# --------------------------------------------------------------------------- #
@router.post(
    "/api/remediation/execute/{recommendation_id}",
    status_code=status.HTTP_200_OK,
)
async def execute_remediation(recommendation_id: str) -> dict:
    """Execute a remediation through its safe path and persist the report.

    Runs the deterministic safety router, then either applies the runbook
    (auto-fix / approved fix, with verification + rollback) or escalates (ticket
    + notifications). The resulting :class:`RemediationResult` is persisted with
    links to the originating Issue, Recommendation and Workload, and a
    ``REMEDIATION_COMPLETED`` event is emitted.
    """
    recommendation = _load_recommendation(recommendation_id)
    workload = workload_service.get_workload(recommendation["workload_id"])
    issue = issue_service.get_issue(recommendation["issue_id"])

    result = report_generator.generate_report(recommendation, workload, issue)
    remediation_service.create_remediation(result)

    await event_bus.publish(
        Event(
            event_type=EventType.REMEDIATION_COMPLETED,
            payload={
                "remediation_id": result.remediation_id,
                "recommendation_id": result.recommendation_id,
                "issue_id": result.issue_id,
                "workload_id": result.workload_id,
                "execution_path": result.execution_path,
                "execution_status": result.execution_status,
            },
        )
    )

    return success(
        data=result.model_dump(mode="json"),
        message=(
            f"Remediation {result.execution_status} via the "
            f"{result.execution_path} path."
        ),
    )


# --------------------------------------------------------------------------- #
# Report detail
# --------------------------------------------------------------------------- #
@router.get(
    "/api/remediation/{remediation_id}/report",
    status_code=status.HTTP_200_OK,
)
async def get_remediation_report(remediation_id: str) -> dict:
    """Return a previously stored remediation report, or HTTP 404."""
    remediation = remediation_service.get_remediation(remediation_id)
    if remediation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Remediation '{remediation_id}' not found.",
        )
    return success(data=remediation, message="Remediation report retrieved.")
