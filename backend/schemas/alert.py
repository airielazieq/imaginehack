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
    # Delivery / suppression metadata (task 16.2). Additive and defaulted so
    # the generation half (task 16.1) keeps building alerts unchanged.
    suppression_count: int = 0
    delivery_attempts: int = 0
    delivered_at: datetime | None = None
    # Delivery SLA / escalation metadata (task 21.1). All additive and
    # defaulted so earlier code paths keep building alerts unchanged.
    # ``delivery_sla_seconds`` is the per-severity SLA target applied to this
    # alert (critical 30s, non-critical 300s). ``first_attempt_at`` /
    # ``last_attempt_at`` bound the delivery window so SLA compliance can be
    # evaluated (delivered_at - first_attempt_at <= delivery_sla_seconds).
    # ``sla_breached`` records that the window was exceeded, and
    # ``escalated`` / ``escalated_at`` record that delivery was escalated to an
    # on-call operator (SLA breach or repeated owner-delivery failure).
    delivery_sla_seconds: float | None = None
    first_attempt_at: datetime | None = None
    last_attempt_at: datetime | None = None
    sla_breached: bool = False
    escalated: bool = False
    escalated_at: datetime | None = None
