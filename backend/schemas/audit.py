"""Pydantic schema for AuditLog."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AuditLog(BaseModel):
    """An immutable audit-trail entry for a platform state transition."""

    audit_id: str
    event_type: str
    actor: str  # "system", "user", "auto_fix", etc.
    workload_id: str
    issue_id: str | None = None
    recommendation_id: str | None = None
    remediation_id: str | None = None
    timestamp: datetime
    previous_status: str | None = None
    new_status: str | None = None
    details: dict
    rollback_note: str | None = None
