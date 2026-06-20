"""Simulated ticketing connector.

Used on escalation paths (Requirement 10.1) and the missing-monitoring path to
open a tracking ticket with full Issue / Recommendation / Workload context. No
external ticketing system is contacted; a deterministic-shaped ticket record is
returned instead.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from backend.connectors.mcp_base import MCPConnector


def _new_ticket_id() -> str:
    """Return a unique, human-readable simulated ticket id."""
    return f"TICKET-{uuid.uuid4().hex[:8].upper()}"


class TicketingConnector(MCPConnector):
    """Simulated ticketing system connector."""

    category = "ticketing"

    def _tool_create_ticket(
        self,
        workload_id: str | None = None,
        title: str | None = None,
        priority: str = "normal",
        assignee: str | None = None,
        **context: Any,
    ) -> dict:
        ticket_id = _new_ticket_id()
        return {
            "ticket_id": ticket_id,
            "workload_id": workload_id,
            "title": title or "Clover remediation follow-up",
            "priority": priority,
            "assignee": assignee,
            "ticket_status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "context": context,
            "note": f"Ticket {ticket_id} created (simulated).",
        }

    def _tool_update_ticket(
        self,
        ticket_id: str | None = None,
        ticket_status: str = "updated",
        **fields: Any,
    ) -> dict:
        return {
            "ticket_id": ticket_id,
            "ticket_status": ticket_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_fields": fields,
            "note": f"Ticket {ticket_id} updated (simulated).",
        }

    def _tool_assign_ticket(
        self,
        ticket_id: str | None = None,
        assignee: str | None = None,
        **params: Any,
    ) -> dict:
        return {
            "ticket_id": ticket_id,
            "assignee": assignee,
            "ticket_status": "assigned",
            "assigned_at": datetime.now(timezone.utc).isoformat(),
            "note": f"Ticket {ticket_id} assigned to {assignee} (simulated).",
            **params,
        }
