"""Audit log API (task 15.2).

Exposes read endpoints over the platform's immutable audit trail
(spec 10 §5, Requirements 15.1, 21.1). The underlying records are written by
``backend/services/audit_service.py`` on each meaningful lifecycle event and
are never mutated.

- ``GET /api/audit-logs``                       - list audit entries, most
  recent first, filterable by ``workload_id``, ``event_type`` and an inclusive
  ``start_date`` / ``end_date`` window.
- ``GET /api/audit-logs/{audit_id}``            - single audit entry (404 if
  absent).
- ``GET /api/issues/{issue_id}/audit-logs``     - all audit entries referencing
  an issue, most recent first.

All responses use the shared success envelope. To match the frontend
(``getAuditLogs`` / ``getAuditLog`` / ``getIssueAuditLogs`` expect the data to
be ``AuditLog[]`` / ``AuditLog`` directly), the list endpoints return a **bare
list** in ``data`` and the detail endpoint returns the single object in
``data`` — no ``{audit_logs, count}`` wrapper.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status

from backend.schemas.api_responses import success
from backend.services import audit_service

logger = logging.getLogger("clover.api.audit")

router = APIRouter(tags=["audit"])


@router.get("/api/audit-logs", status_code=status.HTTP_200_OK)
async def list_audit_logs(
    workload_id: str | None = Query(
        default=None, description="Restrict to a single workload."
    ),
    event_type: str | None = Query(
        default=None,
        description="Restrict to a single event type (e.g. 'issue_detected').",
    ),
    start_date: str | None = Query(
        default=None, description="Inclusive lower bound on timestamp (ISO-8601)."
    ),
    end_date: str | None = Query(
        default=None, description="Inclusive upper bound on timestamp (ISO-8601)."
    ),
) -> dict:
    """List audit entries (most recent first), filtered by the given params."""
    logs = audit_service.list_audit_logs(
        workload_id=workload_id,
        event_type=event_type,
        start_date=start_date,
        end_date=end_date,
    )
    return success(
        data=logs,
        message=f"Retrieved {len(logs)} audit log(s).",
    )


@router.get("/api/audit-logs/{audit_id}", status_code=status.HTTP_200_OK)
async def get_audit_log(audit_id: str) -> dict:
    """Return a single audit entry by id, or HTTP 404 if it does not exist."""
    log = audit_service.get_audit_log(audit_id)
    if log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit log '{audit_id}' not found.",
        )
    return success(data=log, message="Audit log retrieved.")


@router.get("/api/issues/{issue_id}/audit-logs", status_code=status.HTTP_200_OK)
async def list_issue_audit_logs(issue_id: str) -> dict:
    """Return all audit entries referencing an issue, most recent first."""
    logs = audit_service.list_for_issue(issue_id)
    return success(
        data=logs,
        message=f"Retrieved {len(logs)} audit log(s) for issue '{issue_id}'.",
    )
