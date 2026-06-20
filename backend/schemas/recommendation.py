"""Pydantic schemas for Recommendation and its forecast structures."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high", "critical"]
ExecutionMode = Literal[
    "auto_fix", "user_approval_required", "human_escalation_required"
]


class RuleTriggered(BaseModel):
    """The recommendation rule that fired and the conditions it matched."""

    rule_id: str
    conditions_matched: list[str]


class ForecastModelResult(BaseModel):
    """Raw 30-day forecast output from the forecasting model (or fallback)."""

    model_config = {"protected_namespaces": ()}

    model_name: str
    predicted_cost_30d: float
    predicted_energy_kwh_30d: float
    predicted_carbon_kgco2e_30d: float


class ForecastComponent(BaseModel):
    """A single forecast bundle across cost / energy / carbon dimensions."""

    cost_30d: float
    energy_30d_kwh: float
    carbon_30d_kgco2e: float


class OptimizationImpactForecast(BaseModel):
    """Before / after / savings projection for a recommended action."""

    forecast_without_action: ForecastComponent
    forecast_after_action: ForecastComponent
    projected_savings: ForecastComponent


class Recommendation(BaseModel):
    """Module 2 output / Module 3 input."""

    recommendation_id: str
    issue_id: str
    workload_id: str
    recommended_action: str
    action_category: str
    recommendation_type: str
    rule_triggered: RuleTriggered
    forecast_model_result: ForecastModelResult
    optimization_impact_forecast: OptimizationImpactForecast
    risk_level: RiskLevel
    required_execution_mode: ExecutionMode
    approval_required: bool
    mcp_tools: list[str]
    llm_recommendation_explanation: str
    rollback_note: str | None = None
    created_at: datetime
