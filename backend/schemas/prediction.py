"""Pydantic schema for DowntimePrediction."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["low", "medium", "high"]


class DowntimePrediction(BaseModel):
    """Failure probability, timeline and contributing signals for a workload."""

    workload_id: str
    probability: float = Field(ge=0, le=100)
    estimated_time_to_failure: str = Field(..., description="'4h 30m' format")
    primary_signal: str
    secondary_signal: str | None = None
    pattern_match: str | None = None
    confidence: Confidence
    risk_timeline: list[float] = Field(..., description="12 points (hourly)")
    recommended_preemptive_action: str | None = Field(
        default=None, description="Set when probability > 70%"
    )
