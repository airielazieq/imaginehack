"""Detection & Issues API (task 3.5).

Exposes the Module 1 detection endpoints and the issues query surface
(spec 10 §2):

- ``POST /api/detection/run``               - run detection across all workloads.
- ``POST /api/detection/run/{workloadId}``  - run detection for one workload.
- ``GET  /api/issues``                      - list/filter issues.
- ``GET  /api/issues/{id}``                 - issue detail (incl. ml_result + xai).
- ``PATCH /api/issues/{id}/status``         - update an issue's status.

All responses use the shared success/error envelopes. The detection-run
endpoints operate on each workload's most recent telemetry snapshot and reuse
the same pipeline that the ``TELEMETRY_INGESTED`` subscription drives, so
results are consistent regardless of how detection was triggered.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from backend.modules.detection_insight import detector
from backend.schemas.api_responses import success
from backend.schemas.issue import IssueStatus
from backend.services import issue_service, workload_service

logger = logging.getLogger("clover.api.detection")

router = APIRouter(tags=["detection"])


class StatusUpdate(BaseModel):
    """Request body for a status transition."""

    status: IssueStatus


# --------------------------------------------------------------------------- #
# Detection runs
# --------------------------------------------------------------------------- #
@router.post("/api/detection/run", status_code=status.HTTP_200_OK)
async def run_detection_all() -> dict:
    """Run detection across every workload's latest telemetry."""
    issues = await detector.run_all()
    return success(
        data={"issues": issues, "count": len(issues)},
        message=f"Detection run complete; {len(issues)} issue(s) produced.",
    )


@router.post("/api/detection/run/{workload_id}", status_code=status.HTTP_200_OK)
async def run_detection_for_workload(workload_id: str) -> dict:
    """Run detection for a single workload's latest telemetry.

    Returns HTTP 404 if the workload does not exist. When the workload is
    healthy (no rule fired and not anomalous), ``issue`` is ``null``.
    """
    if not workload_service.workload_exists(workload_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workload '{workload_id}' not found.",
        )
    issue = await detector.run_for_workload(workload_id)
    return success(
        data={"workload_id": workload_id, "issue": issue, "detected": issue is not None},
        message=(
            "Issue detected." if issue is not None else "No issue detected (healthy)."
        ),
    )


# --------------------------------------------------------------------------- #
# Issues query surface
# --------------------------------------------------------------------------- #
@router.get("/api/issues", status_code=status.HTTP_200_OK)
async def list_issues(
    issue_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    issue_category: str | None = Query(default=None),
    status: str | None = Query(default=None),  # noqa: A002 - external query name
    workload_id: str | None = Query(default=None),
) -> dict:
    """List all issues, optionally filtered by the supported fields."""
    issues = issue_service.list_issues(
        issue_type=issue_type,
        severity=severity,
        issue_category=issue_category,
        status=status,
        workload_id=workload_id,
    )
    return success(
        data={"issues": issues, "count": len(issues)},
        message=f"Retrieved {len(issues)} issue(s).",
    )


@router.get("/api/issues/{issue_id}", status_code=status.HTTP_200_OK)
async def get_issue(issue_id: str) -> dict:
    """Return a single issue by id, or HTTP 404 if it does not exist."""
    issue = issue_service.get_issue(issue_id)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue '{issue_id}' not found.",
        )
    return success(data=issue, message="Issue retrieved.")


@router.patch("/api/issues/{issue_id}/status", status_code=status.HTTP_200_OK)
async def patch_issue_status(issue_id: str, body: StatusUpdate) -> dict:
    """Update an issue's status, or HTTP 404 if the issue does not exist."""
    updated = issue_service.update_status(issue_id, body.status)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue '{issue_id}' not found.",
        )
    return success(data=updated, message=f"Issue status updated to '{body.status}'.")
