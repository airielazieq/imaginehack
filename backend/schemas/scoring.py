"""Pydantic schemas for PriorityScore and DimensionScores."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DimensionState = Literal["green", "yellow", "red", "gray"]


class PriorityScore(BaseModel):
    """6-factor weighted priority score that drives the composite heatmap."""

    workload_id: str
    score: float = Field(ge=0, le=100, description="0-100, 1 decimal place")
    security_severity: float
    energy_waste: float
    cost_waste: float
    workflow_criticality: float
    environment_type: float
    self_healing_safety: float
    unavailable_factors: list[str] = Field(default_factory=list)
    detection_timestamp: datetime
    computed_at: datetime


class DimensionScore(BaseModel):
    """A single dimension's numeric score plus its state color."""

    score: float = Field(ge=0, le=100)
    state: DimensionState


class DimensionScores(BaseModel):
    """Per-dimension scores that drive the matrix heatmap."""

    workload_id: str
    security: DimensionScore
    energy: DimensionScore
    carbon: DimensionScore
    cost: DimensionScore
    performance: DimensionScore
    monitoring: DimensionScore
