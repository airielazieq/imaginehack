"""Recommendations & Forecast API (task 4.4).

Exposes the Module 2 recommendation/forecast surface (spec 10 section 3):

- ``POST /api/recommendations/generate/{issueId}`` - generate a Recommendation
  on demand for a stored Issue: look up the issue, build the recommendation
  synchronously (rule match -> risk/mode -> forecast -> optimization impact),
  persist it, emit ``RECOMMENDATION_GENERATED``, and return it.
- ``GET  /api/recommendations/{id}``                - recommendation detail
  (incl. ``optimization_impact_forecast``).
- ``POST /api/forecast/{workloadId}``               - run the XGBoost forecaster
  on the workload's latest telemetry and return the 30-day forecast.

All responses use the shared success/error envelopes; unknown issue /
recommendation / workload (or missing telemetry) return HTTP 404.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from backend.modules.next_best_action import nba_pipeline
from backend.modules.next_best_action.xgboost_forecast import forecast_snapshot
from backend.schemas.api_responses import success
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload
from backend.services import (
    issue_service,
    recommendation_service,
    telemetry_service,
    workload_service,
)

logger = logging.getLogger("clover.api.recommendations")

router = APIRouter(tags=["recommendations"])


# --------------------------------------------------------------------------- #
# Generate-on-demand
# --------------------------------------------------------------------------- #
@router.post(
    "/api/recommendations/generate/{issue_id}", status_code=status.HTTP_200_OK
)
async def generate_recommendation(issue_id: str) -> dict:
    """Generate (or regenerate) a Recommendation for an Issue.

    Returns HTTP 404 if the issue does not exist, or HTTP 422 if no
    recommendation rule covers the issue type / no telemetry is available to
    forecast against.
    """
    if issue_service.get_issue(issue_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue '{issue_id}' not found.",
        )

    recommendation = await nba_pipeline.generate_for_issue_id(issue_id)
    if recommendation is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Could not generate a recommendation for issue '{issue_id}' "
                "(no matching rule or no telemetry available)."
            ),
        )

    return success(
        data=recommendation.model_dump(mode="json"),
        message="Recommendation generated.",
    )


# --------------------------------------------------------------------------- #
# Recommendation detail
# --------------------------------------------------------------------------- #
@router.get("/api/recommendations/{recommendation_id}", status_code=status.HTTP_200_OK)
async def get_recommendation(recommendation_id: str) -> dict:
    """Return a single recommendation by id, or HTTP 404 if it does not exist."""
    recommendation = recommendation_service.get_recommendation(recommendation_id)
    if recommendation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recommendation '{recommendation_id}' not found.",
        )
    return success(data=recommendation, message="Recommendation retrieved.")


# --------------------------------------------------------------------------- #
# Forecast
# --------------------------------------------------------------------------- #
@router.post("/api/forecast/{workload_id}", status_code=status.HTTP_200_OK)
async def forecast_workload(workload_id: str) -> dict:
    """Run the 30-day forecaster on a workload's latest telemetry.

    Returns HTTP 404 if the workload does not exist or has no telemetry yet.
    """
    raw_workload = workload_service.get_workload(workload_id)
    if raw_workload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workload '{workload_id}' not found.",
        )

    history = telemetry_service.get_telemetry_history(workload_id, limit=1)
    if not history:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No telemetry available for workload '{workload_id}'.",
        )

    telemetry = TelemetrySnapshot(**history[0])
    try:
        workload = Workload(**raw_workload)
    except Exception:  # noqa: BLE001 - forecast still works without workload context
        workload = None

    forecast = forecast_snapshot(telemetry, workload)
    return success(
        data={
            "workload_id": workload_id,
            "forecast": forecast.model_dump(mode="json"),
        },
        message="Forecast produced.",
    )
