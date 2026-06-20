"""Pydantic schemas for RemediationResult and its execution structures."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ExecutionPath = Literal["auto_fix", "user_approved", "human_escalation"]
ExecutionStatus = Literal[
    "not_started",
    "pending_approval",
    "in_progress",
    "completed",
    "failed",
    "escalated",
    "rejected",
]
MCPToolStatus = Literal["success", "failed", "skipped"]
ApprovalType = Literal["auto", "user_approved", "escalated"]
PolicyCompliance = Literal["compliant", "violation_overridden", "exception"]
VerificationResult = Literal["passed", "failed", "skipped"]


class MCPToolExecution(BaseModel):
    """A single simulated MCP tool invocation within a runbook."""

    tool: str
    category: str
    input: dict
    output: dict
    duration_ms: int
    status: MCPToolStatus


class SafetyDecision(BaseModel):
    """The safety router's rationale for the chosen execution path."""

    why_safe: str
    approval_required: bool
    rollback_available: bool


class AuditCompliance(BaseModel):
    """Compliance metadata attached to a remediation result."""

    approval_type: ApprovalType
    policy_compliance: PolicyCompliance
    rollback_available: bool
    retention_expires: datetime
    persistent_data_modified: bool


class RemediationResult(BaseModel):
    """Module 3 output: full remediation record + report."""

    remediation_id: str
    recommendation_id: str
    issue_id: str
    workload_id: str
    execution_path: ExecutionPath
    execution_status: ExecutionStatus
    action_taken: dict
    reason_for_action: str
    safety_decision: SafetyDecision
    ai_decision_steps: list[dict]
    mcp_tools_executed: list[MCPToolExecution]
    impact_result: dict  # before / after / simulated_savings
    execution_timeline: list[dict]
    audit_compliance: AuditCompliance
    user_facing_report: str
    rollback_triggered: bool
    verification_result: VerificationResult
