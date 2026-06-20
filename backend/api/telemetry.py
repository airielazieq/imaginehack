"""Telemetry ingestion API (Module 1 entry point).

Exposes two endpoints:

- ``POST /api/telemetry/ingest`` - ingest a single :class:`TelemetrySnapshot`.
- ``POST /api/telemetry/bulk-ingest`` - ingest a list of snapshots.

For each accepted snapshot the endpoint:

1. Validates it against :class:`TelemetrySnapshot` (Pydantic). Out-of-bounds
   values raise ``RequestValidationError`` which the app's handler surfaces as
   an HTTP 422 ``VALIDATION_ERROR`` envelope (Requirement 1.2).
2. Persists the snapshot to the ``telemetry`` table in SQLite (Requirement 1.1).
3. Emits a ``TELEMETRY_INGESTED`` event on the async event bus so the
   Detection_Engine pipeline can react (Requirement 1.3).

Persistence and event emission are independent per snapshot, allowing bulk
ingestion of telemetry for many concurrent workloads (Requirement 1.4).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, status

from backend.core.event_bus import Event, EventType, event_bus
from backend.schemas.api_responses import success
from backend.schemas.telemetry import TelemetrySnapshot
from backend.services.telemetry_service import persist_snapshot as _persist_snapshot

logger = logging.getLogger("clover.api.telemetry")

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


async def _emit_ingested(snapshot: TelemetrySnapshot) -> None:
    """Emit a TELEMETRY_INGESTED event to trigger the detection pipeline."""
    await event_bus.publish(
        Event(
            event_type=EventType.TELEMETRY_INGESTED,
            payload={
                "workload_id": snapshot.workload_id,
                "snapshot": snapshot.model_dump(mode="json"),
            },
        )
    )


@router.post("/ingest", status_code=status.HTTP_200_OK)
async def ingest_telemetry(snapshot: TelemetrySnapshot) -> dict:
    """Ingest a single telemetry snapshot.

    Validation is handled by FastAPI/Pydantic before this handler runs;
    invalid payloads never reach here and are returned as HTTP 422.
    """
    telemetry_id = _persist_snapshot(snapshot)
    await _emit_ingested(snapshot)
    logger.info(
        "Ingested telemetry id=%s for workload=%s", telemetry_id, snapshot.workload_id
    )
    return success(
        data={
            "telemetry_id": telemetry_id,
            "workload_id": snapshot.workload_id,
        },
        message="Telemetry snapshot ingested.",
    )


@router.post("/bulk-ingest", status_code=status.HTTP_200_OK)
async def bulk_ingest_telemetry(snapshots: list[TelemetrySnapshot]) -> dict:
    """Ingest a list of telemetry snapshots.

    Each snapshot is validated by Pydantic; if any element is out of bounds the
    whole request is rejected with HTTP 422 before this handler runs. Accepted
    snapshots are persisted and trigger detection independently.
    """
    results = []
    for snapshot in snapshots:
        telemetry_id = _persist_snapshot(snapshot)
        await _emit_ingested(snapshot)
        results.append(
            {"telemetry_id": telemetry_id, "workload_id": snapshot.workload_id}
        )
    logger.info("Bulk-ingested %d telemetry snapshots", len(results))
    return success(
        data={"ingested_count": len(results), "items": results},
        message=f"Ingested {len(results)} telemetry snapshot(s).",
    )
