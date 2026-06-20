"""Simulated notification connector.

Delivers notifications to the workload owner team, the security team (for
security issues), and the devops/SRE team (Requirement 10.2). Also supports
escalating directly to an on-call operator. Each tool returns a simulated
delivery record rather than contacting a real channel.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from backend.connectors.mcp_base import MCPConnector


def _delivery_record(recipient: str, channel: str, message: str | None) -> dict:
    """Build a deterministic-shaped simulated delivery record."""
    delivery_id = f"NOTIF-{uuid.uuid4().hex[:8].upper()}"
    return {
        "delivery_id": delivery_id,
        "recipient": recipient,
        "channel": channel,
        "message": message or "",
        "delivery_status": "delivered",
        "delivered_at": datetime.now(timezone.utc).isoformat(),
        "note": f"Notification {delivery_id} delivered to {recipient} (simulated).",
    }


class NotificationConnector(MCPConnector):
    """Simulated multi-channel notification connector."""

    category = "notification"

    def _tool_notify_owner(
        self,
        owner_team: str | None = None,
        workload_id: str | None = None,
        message: str | None = None,
        channel: str = "email",
        **params: Any,
    ) -> dict:
        record = _delivery_record(owner_team or "owner_team", channel, message)
        record["workload_id"] = workload_id
        record.update(params)
        return record

    def _tool_notify_security_team(
        self,
        workload_id: str | None = None,
        message: str | None = None,
        channel: str = "pager",
        **params: Any,
    ) -> dict:
        record = _delivery_record("security_team", channel, message)
        record["workload_id"] = workload_id
        record.update(params)
        return record

    def _tool_notify_devops_team(
        self,
        workload_id: str | None = None,
        message: str | None = None,
        channel: str = "slack",
        **params: Any,
    ) -> dict:
        record = _delivery_record("devops_team", channel, message)
        record["workload_id"] = workload_id
        record.update(params)
        return record

    def _tool_escalate_to_operator(
        self,
        workload_id: str | None = None,
        message: str | None = None,
        channel: str = "pager",
        **params: Any,
    ) -> dict:
        record = _delivery_record("on_call_operator", channel, message)
        record["workload_id"] = workload_id
        record["escalation"] = True
        record.update(params)
        return record
