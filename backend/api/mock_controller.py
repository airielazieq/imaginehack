"""Mock controller API (task 2.3).

Exposes demo-control endpoints backed by the singleton ``mock_data_service``.
These power the demo console: listing/triggering engineered scenarios,
resetting all workloads to a healthy baseline, and toggling the continuous
telemetry stream (Requirements 19.1-19.4).

- ``GET  /api/mock/scenarios``            - list demo scenarios (no payload).
- ``POST /api/mock/trigger/{scenarioId}`` - inject a scenario's telemetry;
  404 ``NOT_FOUND`` envelope for an unknown scenario.
- ``POST /api/mock/reset``                - reset every workload to healthy.
- ``POST /api/mock/stream/start``         - start the live telemetry stream.
- ``POST /api/mock/stream/stop``          - stop the live telemetry stream.
- ``GET  /api/mock/status``               - current controller/stream status.

All responses use the shared success/error envelopes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from backend.schemas.api_responses import success
from backend.services.mock_data_service import mock_data_service

logger = logging.getLogger("clover.api.mock_controller")

router = APIRouter(prefix="/api/mock", tags=["mock"])


@router.get("/scenarios", status_code=status.HTTP_200_OK)
async def list_scenarios() -> dict:
    """List the available demo scenarios (telemetry payload withheld)."""
    scenarios = mock_data_service.list_scenarios()
    return success(
        data={"scenarios": scenarios, "count": len(scenarios)},
        message=f"Retrieved {len(scenarios)} scenario(s).",
    )


@router.post("/trigger/{scenario_id}", status_code=status.HTTP_200_OK)
async def trigger_scenario(scenario_id: str) -> dict:
    """Trigger a demo scenario, injecting its engineered telemetry snapshot.

    Returns HTTP 404 ``NOT_FOUND`` if the scenario id is unknown.
    """
    try:
        result = await mock_data_service.trigger_scenario(scenario_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_id}' not found.",
        )
    return success(data=result, message=f"Triggered scenario '{scenario_id}'.")


@router.post("/reset", status_code=status.HTTP_200_OK)
async def reset() -> dict:
    """Reset every workload to its healthy baseline and clear demo state."""
    result = await mock_data_service.reset()
    return success(data=result, message="Reset to healthy baseline complete.")


@router.post("/stream/start", status_code=status.HTTP_200_OK)
async def start_stream() -> dict:
    """Start the continuous telemetry stream (no-op if already running)."""
    started = await mock_data_service.start_stream()
    return success(
        data={"started": started, "streaming": mock_data_service.is_streaming},
        message="Telemetry stream started." if started else "Telemetry stream already running.",
    )


@router.post("/stream/stop", status_code=status.HTTP_200_OK)
async def stop_stream() -> dict:
    """Stop the continuous telemetry stream (no-op if not running)."""
    stopped = await mock_data_service.stop_stream()
    return success(
        data={"stopped": stopped, "streaming": mock_data_service.is_streaming},
        message="Telemetry stream stopped." if stopped else "Telemetry stream was not running.",
    )


@router.get("/status", status_code=status.HTTP_200_OK)
async def get_status() -> dict:
    """Return the current mock controller / stream status."""
    return success(data=mock_data_service.status(), message="Mock controller status.")
