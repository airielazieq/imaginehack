"""Pydantic schema for Alert."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]
AlertStatus = Literal["active", "resolved", "delivery_failed", "suppressed"]


class Alert(BaseModel):
    """Threshold-based alert with suppression / retry / SLA metadata."""

    alert_id: str
    title: str = Field(max_length=120)
    workload_id: str
    construction_workflow: str
    severity: Severity
    security_impact: str = Field(max_length=500)
    energy_impact: str = Field(max_length=500)
    cost_impact: str = Field(max_length=500)
    recommended_action: str
    self_healing_eligible: bool
    status: AlertStatus
    priority_score: float
    created_at: datetime
    resolved_at: datetime | None = None
    resolution_method: str | None = None
    suppressed_until: datetime | None = None
