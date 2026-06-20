"""MCP activity-log API (task 18.2).

Exposes a read endpoint over the platform's MCP connector activity log — every
simulated MCP tool invocation (cloud, ticketing, notification, audit) recorded
centrally at the :class:`~backend.connectors.ConnectorRegistry` dispatch
chokepoint by ``backend/services/mcp_log_service.py``.

- ``GET /api/mcp/log`` - list MCP activity-log entries, most-recent-first,
  optionally filtered by ``workload_id``.

To match the frontend (``getMCPLog`` expects ``MCPLogEntry[]`` directly), the
endpoint returns a **bare list** in the ``data`` field of the success envelope.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, status

from backend.schemas.api_responses import success
from backend.services import mcp_log_service

logger = logging.getLogger("clover.api.mcp_log")

router = APIRouter(tags=["mcp"])


@router.get("/api/mcp/log", status_code=status.HTTP_200_OK)
async def list_mcp_log(
    workload_id: str | None = Query(
        default=None, description="Restrict to invocations for a single workload."
    ),
) -> dict:
    """List MCP activity-log entries (most recent first), optionally filtered."""
    entries = mcp_log_service.list_mcp_log(workload_id=workload_id)
    return success(
        data=entries,
        message=f"Retrieved {len(entries)} MCP activity-log entr(ies).",
    )
