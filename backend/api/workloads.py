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
import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status

from backend.core.event_bus import Event, EventType, event_bus
from backend.modules.downtime_prediction import predictor
from backend.schemas.api_responses import success
from backend.services import telemetry_service, workload_service

logger = logging.getLogger("clover.api.workloads")

router = APIRouter(prefix="/api/workloads", tags=["workloads"])

# Number of daily segments in the uptime history window (Requirement 17.3).
_UPTIME_WINDOW_DAYS = 90


def _build_uptime_history(workload_id: str) -> dict:
    """Generate a deterministic 90-day uptime history for a workload.

    The history is synthetic but stable: the RNG is seeded with the
    ``workload_id`` so repeated calls (and the overall summary) are identical
    across requests. Each of the 90 segments carries a calendar ``date``, an
    ``uptime_percent`` for that day, and a ``status`` of ``up``/``degraded``/
    ``down`` derived from that percentage.
    """
    rng = random.Random(workload_id)
    today = datetime.now(timezone.utc).date()

    segments: list[dict] = []
    for offset in range(_UPTIME_WINDOW_DAYS - 1, -1, -1):
        day = today - timedelta(days=offset)
        # Mostly-healthy distribution: most days at/near 100%, occasional dips.
        roll = rng.random()
        if roll < 0.82:  # healthy day
            uptime_percent = round(rng.uniform(99.5, 100.0), 2)
        elif roll < 0.95:  # degraded day
            uptime_percent = round(rng.uniform(95.0, 99.49), 2)
        else:  # outage day
            uptime_percent = round(rng.uniform(80.0, 94.99), 2)

        if uptime_percent >= 99.5:
            seg_status = "up"
        elif uptime_percent >= 95.0:
            seg_status = "degraded"
        else:
            seg_status = "down"

        segments.append(
            {
                "date": day.isoformat(),
                "uptime_percent": uptime_percent,
                "status": seg_status,
            }
        )

    overall = round(
        sum(seg["uptime_percent"] for seg in segments) / len(segments), 2
    )
    return {
        "workload_id": workload_id,
        "segments": segments,
        "overall_uptime_percent": overall,
        "window_days": _UPTIME_WINDOW_DAYS,
        "count": len(segments),
    }


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


@router.get("/{workload_id}/uptime", status_code=status.HTTP_200_OK)
async def get_workload_uptime(workload_id: str) -> dict:
    """Return the 90-day uptime history for a workload (Requirement 17.3).

    Produces 90 daily availability segments (oldest first), each with a date,
    an uptime percentage, and an ``up``/``degraded``/``down`` status, plus an
    overall uptime percentage summary. The history is synthetic but
    deterministic per workload, so repeated calls return identical data.
    Returns HTTP 404 if the workload does not exist.
    """
    if not workload_service.workload_exists(workload_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workload '{workload_id}' not found.",
        )
    history = _build_uptime_history(workload_id)
    return success(
        data=history,
        message=f"Retrieved {history['count']} uptime segment(s).",
    )


@router.get("/{workload_id}/prediction", status_code=status.HTTP_200_OK)
async def get_workload_prediction(workload_id: str) -> dict:
    """Return the downtime prediction for a workload (Requirement 14).

    Computes failure probability, estimated time-to-failure, confidence,
    contributing signals, and a 12-point hourly risk timeline from telemetry
    trends. When the probability exceeds 70%, a preemptive Recommendation is
    triggered via the NBA engine (best-effort) and ``PREDICTION_UPDATED`` is
    announced. Returns HTTP 404 if the workload does not exist.
    """
    if not workload_service.workload_exists(workload_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workload '{workload_id}' not found.",
        )

    history = telemetry_service.get_telemetry_history(workload_id)
    prediction = predictor.predict(workload_id, history)

    # Requirement 14.3: preemptive Recommendation when probability > 70%.
    # Best-effort and non-fatal - a downstream failure must not break the read.
    await predictor.maybe_trigger_preemptive(prediction)

    # Announce the fresh prediction for any interested subscribers (best-effort).
    try:
        await event_bus.publish(
            Event(
                event_type=EventType.PREDICTION_UPDATED,
                payload={
                    "workload_id": workload_id,
                    "prediction": prediction.model_dump(mode="json"),
                },
            )
        )
    except Exception:  # noqa: BLE001 - event publication must not break the read
        logger.exception("Failed to publish PREDICTION_UPDATED for %s", workload_id)

    return success(
        data=prediction.model_dump(mode="json"),
        message="Downtime prediction computed.",
    )
