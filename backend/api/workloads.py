"""Workloads API.

Exposes read endpoints for the canonical Workload entity and its telemetry
history (Requirement 21.1):

- ``GET /api/workloads``                  - list all workloads.
- ``GET /api/workloads/{workload_id}``    - single workload detail (404 if absent).
- ``GET /api/workloads/{workload_id}/telemetry`` - telemetry history, most
  recent first, with an optional ``limit`` query parameter.

All responses use the shared success/error envelopes. Missing workloads return
an HTTP 404 ``NOT_FOUND`` envelope via the application's exception handler.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status

from backend.schemas.api_responses import success
from backend.services import telemetry_service, workload_service

logger = logging.getLogger("clover.api.workloads")

router = APIRouter(prefix="/api/workloads", tags=["workloads"])


@router.get("", status_code=status.HTTP_200_OK)
@router.get("/", status_code=status.HTTP_200_OK)
async def list_workloads() -> dict:
    """List all workloads."""
    workloads = workload_service.list_workloads()
    return success(
        data={"workloads": workloads, "count": len(workloads)},
        message=f"Retrieved {len(workloads)} workload(s).",
    )


@router.get("/{workload_id}", status_code=status.HTTP_200_OK)
async def get_workload(workload_id: str) -> dict:
    """Return a single workload by id, or HTTP 404 if it does not exist."""
    workload = workload_service.get_workload(workload_id)
    if workload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workload '{workload_id}' not found.",
        )
    return success(data=workload, message="Workload retrieved.")


@router.get("/{workload_id}/telemetry", status_code=status.HTTP_200_OK)
async def get_workload_telemetry(
    workload_id: str,
    limit: int | None = Query(
        default=None,
        ge=1,
        le=1000,
        description="Maximum number of snapshots to return (most recent first).",
    ),
) -> dict:
    """Return telemetry history for a workload, most recent first.

    Returns HTTP 404 if the workload does not exist. An optional ``limit``
    caps the number of returned snapshots.
    """
    if not workload_service.workload_exists(workload_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workload '{workload_id}' not found.",
        )
    history = telemetry_service.get_telemetry_history(workload_id, limit=limit)
    return success(
        data={
            "workload_id": workload_id,
            "telemetry": history,
            "count": len(history),
        },
        message=f"Retrieved {len(history)} telemetry snapshot(s).",
    )
