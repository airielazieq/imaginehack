"""Pydantic schemas for the Clover Cloud Intelligence Platform data models."""
from __future__ import annotations

from .alert import Alert
from .api_responses import ErrorResponse, SuccessResponse, error, success
from .audit import AuditLog
from .issue import (
    EstimatedImpact,
    Issue,
    MLResult,
    XAIExplanation,
    XAIFactor,
)
from .prediction import DowntimePrediction
from .recommendation import (
    ForecastComponent,
    ForecastModelResult,
    OptimizationImpactForecast,
    Recommendation,
    RuleTriggered,
)
from .remediation import (
    AuditCompliance,
    MCPToolExecution,
    RemediationResult,
    SafetyDecision,
)
from .scoring import DimensionScore, DimensionScores, PriorityScore
from .telemetry import TelemetrySnapshot
from .workload import Workload

__all__ = [
    # workload
    "Workload",
    # telemetry
    "TelemetrySnapshot",
    # issue
    "Issue",
    "MLResult",
    "XAIExplanation",
    "XAIFactor",
    "EstimatedImpact",
    # recommendation
    "Recommendation",
    "RuleTriggered",
    "ForecastModelResult",
    "ForecastComponent",
    "OptimizationImpactForecast",
    # remediation
    "RemediationResult",
    "MCPToolExecution",
    "SafetyDecision",
    "AuditCompliance",
    # scoring
    "PriorityScore",
    "DimensionScore",
    "DimensionScores",
    # alert
    "Alert",
    # audit
    "AuditLog",
    # prediction
    "DowntimePrediction",
    # api responses
    "SuccessResponse",
    "ErrorResponse",
    "success",
    "error",
]
