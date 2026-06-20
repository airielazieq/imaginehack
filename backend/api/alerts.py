"""Alerts API (task 16.2).

Exposes the read endpoint over the Alert System's generated alerts
(spec 10 §5, design "Scoring, Alerts & Audit", Requirement 13). Alerts are
produced by ``backend/modules/alerts/alert_engine.py`` (generation), delivered
and auto-resolved by ``backend/modules/alerts/delivery.py``, and deduplicated by
``backend/modules/alerts/suppression.py``.

- ``GET /api/alerts`` - list alerts, most recent first, filterable by
  ``workload_id`` (per the spec contract ``/api/alerts[?workload_id=]``) and,
  for convenience, ``severity`` and ``status``.

To match the frontend (``getAlerts`` in ``frontend/src/api/endpoints.ts``
expects the data to be ``Alert[]`` directly via the unwrapped ``.data``), this
endpoint returns a **bare list** in ``data`` — no ``{alerts, count}`` wrapper —
mirroring the audit-logs list endpoint.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, status

from backend.schemas.api_responses import success
from backend.services import alert_service

logger = logging.getLogger("clover.api.alerts")

router = APIRouter(tags=["alerts"])


@router.get("/api/alerts", status_code=status.HTTP_200_OK)
async def list_alerts(
    workload_id: str | None = Query(
        default=None, description="Restrict to a single workload."
    ),
    severity: str | None = Query(
        default=None,
        description="Restrict to a single severity (low/medium/high/critical).",
    ),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Restrict to a single status (active/resolved/delivery_failed/suppressed).",
    ),
) -> dict:
    """List alerts (most recent first), filtered by the given params."""
    alerts = alert_service.list_alerts(
        workload_id=workload_id,
        severity=severity,
        status=status_filter,
    )
    return success(
        data=alerts,
        message=f"Retrieved {len(alerts)} alert(s).",
    )
