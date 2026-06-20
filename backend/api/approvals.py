"""Approval queue API (task 5.4).

Exposes the global remediation approval queue (spec 10 section 4):

- ``GET  /api/approvals``            - list the queue, severity-sorted
  (Critical -> High -> Medium -> Low), with live escalation countdowns.
- ``POST /api/approvals/{id}/approve`` - approve a pending item (optionally
  selecting a subset of MCP tools to run).
- ``POST /api/approvals/{id}/deny``    - deny a pending item.
- ``POST /api/approvals/{id}/snooze``  - push the escalation countdown out
  (defaults to the configured snooze window, 30 minutes).

All responses use the shared success/error envelopes. An unknown approval id
returns HTTP 404; acting on an item that has already reached a terminal state
returns HTTP 409.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException, status

from backend.modules.self_healing.approval_queue import (
    InvalidTransition,
    approval_queue,
)
from backend.schemas.api_responses import success
from backend.services import issue_service

logger = logging.getLogger("clover.api.approvals")

router = APIRouter(tags=["approvals"])


def _sync_issue_status(item, new_status: str) -> None:
    """Reflect an approval decision on the originating issue (best-effort).

    Approving moves the issue to ``approved``; denying moves it to ``rejected``.
    This keeps the issue's status — which the UI's Self-Healing tab and status
    badges read — in step with the approval queue. A failure here must never
    fail the approve/deny request.
    """
    if item is None:
        return
    try:
        issue_service.update_status(item.issue_id, new_status)
    except Exception:  # noqa: BLE001 - status write-back is best-effort
        logger.exception(
            "Failed to sync issue %s to %s after approval decision",
            item.issue_id,
            new_status,
        )


@router.get("/api/approvals", status_code=status.HTTP_200_OK)
async def list_approvals(include_resolved: bool = False) -> dict:
    """Return the global approval queue sorted by severity (Critical first)."""
    items = approval_queue.list_items(include_resolved=include_resolved)
    return success(
        data={
            "approvals": [item.to_dict() for item in items],
            "count": len(items),
        },
        message="Approval queue retrieved.",
    )


@router.post("/api/approvals/{approval_id}/approve", status_code=status.HTTP_200_OK)
async def approve_approval(
    approval_id: str,
    body: dict | None = Body(default=None),
) -> dict:
    """Approve a queued remediation.

    Accepts an optional ``{"selected_mcp_tools": [...]}`` body to restrict which
    MCP tools the subsequent execution should run.
    """
    selected = None
    if body and isinstance(body.get("selected_mcp_tools"), list):
        selected = [str(t) for t in body["selected_mcp_tools"]]

    if approval_queue.get(approval_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval '{approval_id}' not found.",
        )
    try:
        item = approval_queue.approve(approval_id, selected_mcp_tools=selected)
    except InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    _sync_issue_status(item, "approved")
    return success(data=item.to_dict(), message="Recommendation approved.")


@router.post("/api/approvals/{approval_id}/deny", status_code=status.HTTP_200_OK)
async def deny_approval(approval_id: str) -> dict:
    """Deny a queued remediation."""
    if approval_queue.get(approval_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval '{approval_id}' not found.",
        )
    try:
        item = approval_queue.deny(approval_id)
    except InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    _sync_issue_status(item, "rejected")
    return success(data=item.to_dict(), message="Recommendation denied.")


@router.post("/api/approvals/{approval_id}/snooze", status_code=status.HTTP_200_OK)
async def snooze_approval(
    approval_id: str,
    body: dict | None = Body(default=None),
) -> dict:
    """Snooze the escalation countdown for a queued remediation.

    Accepts an optional ``{"minutes": <int>}`` body; defaults to the configured
    snooze window (30 minutes).
    """
    minutes = None
    if body and body.get("minutes") is not None:
        try:
            minutes = int(body["minutes"])
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'minutes' must be an integer.",
            )
        if minutes <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'minutes' must be a positive integer.",
            )

    if approval_queue.get(approval_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval '{approval_id}' not found.",
        )
    try:
        item = approval_queue.snooze(approval_id, minutes=minutes)
    except InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return success(data=item.to_dict(), message="Escalation timer snoozed.")
