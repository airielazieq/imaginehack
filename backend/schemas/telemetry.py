"""Pydantic schema for TelemetrySnapshot (Module 1 input).

Bounds are enforced on ingest. Out-of-bounds values raise a Pydantic
``ValidationError`` which the API layer surfaces as HTTP 422.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

VulnerabilitySeverity = Literal["none", "low", "medium", "high", "critical"]

# Shared cost bound used for all monetary fields.
_COST_MAX = 999999.99


class TelemetrySnapshot(BaseModel):
    """A single point-in-time telemetry reading for a workload.

    Numeric bounds (validated on ingest):
      - cpu / memory / error_rate are percentages in [0, 100]
      - counts and absolute resource values are >= 0
      - cost fields are in [0, 999999.99]
    """

    model_config = {"extra": "forbid"}

    workload_id: str

    # Utilization percentages.
    cpu_usage_percent: float = Field(ge=0, le=100)
    memory_usage_percent: float = Field(ge=0, le=100)

    # Resource / activity counters.
    storage_gb: float = Field(ge=0)
    runtime_hours_24h: float = Field(ge=0)
    request_count_24h: int = Field(ge=0)

    # Performance.
    error_rate_percent: float = Field(ge=0, le=100)
    latency_ms: float = Field(ge=0)

    # Security posture.
    public_exposure: bool
    public_storage: bool
    vulnerability_severity: VulnerabilitySeverity
    critical_vulnerability_count: int = Field(ge=0)
    access_anomaly_detected: bool
    monitoring_enabled: bool

    # Cost.
    cost_per_hour: float = Field(ge=0, le=_COST_MAX)
    cost_24h: float = Field(ge=0, le=_COST_MAX)
    cost_30d_forecast: float = Field(ge=0, le=_COST_MAX)

    # GreenOps.
    energy_kwh_24h: float = Field(ge=0)
    carbon_kgco2e_24h: float = Field(ge=0)
    carbon_intensity_gco2_per_kwh: float = Field(ge=0)

    timestamp: datetime
