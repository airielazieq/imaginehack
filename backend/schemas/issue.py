"""Pydantic schemas for Issue and its nested detection structures."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

IssueCategory = Literal[
    "security",
    "cost",
    "energy",
    "carbon",
    "performance",
    "monitoring",
    "cost_energy_carbon",
]
Severity = Literal["low", "medium", "high", "critical"]
RiskLevel = Literal["low", "medium", "high"]
IssueStatus = Literal[
    "new",
    "recommended",
    "pending_approval",
    "approved",
    "auto_fixed",
    "remediated",
    "escalated",
    "rejected",
    "dismissed",
]


class MLResult(BaseModel):
    """Output of the anomaly detection model (or its fallback)."""

    model_config = {"protected_namespaces": ()}

    model_name: str = Field(..., description="'Isolation Forest' or fallback name")
    anomaly_score: float
    is_anomaly: bool


class XAIFactor(BaseModel):
    """A single feature contribution within an XAI explanation."""

    feature: str
    value: float | str
    impact: str = Field(..., description="Plain-language impact description")


class XAIExplanation(BaseModel):
    """Explainable-AI summary of top contributing factors."""

    method: str = Field(..., description="e.g. 'SHAP-style feature contribution'")
    top_contributing_factors: list[XAIFactor]


class EstimatedImpact(BaseModel):
    """Per-dimension risk assessment for an issue."""

    cost_risk: RiskLevel
    energy_risk: RiskLevel
    carbon_risk: RiskLevel
    security_risk: RiskLevel
    workflow_disruption_risk: RiskLevel


class Issue(BaseModel):
    """Detection output / Module 2 input."""

    model_config = {"protected_namespaces": ()}

    issue_id: str
    workload_id: str
    issue_type: str = Field(..., description="One of 7+ defined types")
    issue_category: IssueCategory
    severity: Severity
    confidence_score: float = Field(ge=0, le=1)
    detected_evidence: dict
    ml_result: MLResult
    xai_explanation: XAIExplanation
    llm_user_explanation: str
    estimated_impact: EstimatedImpact
    status: IssueStatus
    detected_at: datetime
