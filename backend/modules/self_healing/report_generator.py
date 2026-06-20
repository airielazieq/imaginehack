"""Remediation report generator for Module 3 (Guardrailed Self-Healing) — task 5.5.

This is the final assembly stage of the self-healing module. It pulls together
the outputs of the deterministic safety router (task 5.1), the runbook executor
+ verification + rollback (task 5.3) and the simulated MCP connectors (task 5.2)
into a single, fully-populated
:class:`~backend.schemas.remediation.RemediationResult` — the record the
remediation API persists and surfaces to operators (Requirements 8.4, 11.1,
11.2, 11.3).

A report is produced after **every** completion, regardless of execution path:

* ``auto_fix``            — execute the runbook, verify, roll back + escalate on
  failure.
* ``user_approved``       — same execution guarantees as auto-fix, reached only
  once a human has authorised the action. The remediation ``execute`` endpoint
  enforces this: a ``user_approval_required`` remediation is refused (HTTP 409)
  until its item in the global approval queue has been explicitly approved.
* ``human_escalation``    — no fix is applied; instead a tracking ticket is
  opened and the owner / security teams are notified (Requirements 10.1, 10.2).

Every result carries:

* the chosen ``execution_path`` and ``execution_status``,
* the :class:`SafetyDecision` rationale (deterministic, never LLM-derived),
* ``ai_decision_steps`` with timestamps,
* ``mcp_tools_executed`` (the full list of :class:`MCPToolExecution`),
* the before / after / simulated-savings ``impact_result``,
* a complete ``execution_timeline``,
* an :class:`AuditCompliance` record, and
* a plain-language ``user_facing_report`` narrative.

Nothing in this module reaches a real cloud, and (apart from the wall-clock
timestamps stamped onto the timeline) it performs no I/O — persistence and event
emission are the API/service layer's responsibility.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.connectors import ConnectorRegistry
from backend.modules.self_healing.healer import run_auto_fix
from backend.modules.self_healing.safety_router import (
    RemediationContext,
    SafetyRoutingDecision,
    build_remediation_context,
    route,
)
from backend.schemas.remediation import (
    AuditCompliance,
    MCPToolExecution,
    RemediationResult,
)

logger = logging.getLogger("clover.self_healing.report_generator")

# Map the safety router's path vocabulary onto the persisted RemediationResult
# execution_path vocabulary (design.md "Remediation" schema).
_ROUTER_PATH_TO_RESULT_PATH: dict[str, str] = {
    "auto_fix": "auto_fix",
    "user_approval_required": "user_approved",
    "human_escalation_required": "human_escalation",
}

# Map a result execution_path onto its AuditCompliance approval_type.
_PATH_TO_APPROVAL_TYPE: dict[str, str] = {
    "auto_fix": "auto",
    "user_approved": "user_approved",
    "human_escalation": "escalated",
}

# How long a remediation record is retained for compliance (audit retention).
_RETENTION_DAYS = 365


def _as_dict(obj: Any) -> dict[str, Any]:
    """Coerce a Pydantic model / mapping / object into a plain dict."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    raise TypeError(f"Cannot read remediation inputs from {type(obj)!r}")


def _new_remediation_id() -> str:
    return f"REM-{uuid.uuid4().hex[:12].upper()}"


# --------------------------------------------------------------------------- #
# Safety-fact derivation
# --------------------------------------------------------------------------- #
def derive_action_properties(
    recommendation: Any,
    workload: Any | None = None,
    issue: Any | None = None,
) -> dict[str, Any]:
    """Infer the concrete safety facts for a recommendation's action.

    The :class:`Recommendation` carries *what* should be done; the safety router
    needs the *properties* of that action (reversibility, whether it touches a
    security/network policy, sensitive data, etc.). Those are derived
    deterministically from the recommendation's ``action_category`` /
    ``recommendation_type`` and its ``rollback_note``, plus the workload
    environment and the originating issue.

    The returned mapping is suitable as ``action_properties`` for
    :func:`~backend.modules.self_healing.safety_router.build_remediation_context`.
    """
    rec = _as_dict(recommendation)
    wl = _as_dict(workload)
    iss = _as_dict(issue)

    category = rec.get("action_category")
    rec_type = rec.get("recommendation_type")
    environment = wl.get("environment")
    rollback_note = rec.get("rollback_note")
    risk_level = rec.get("risk_level")

    is_security = category == "security" or rec_type == "restrict_access"
    is_incident = rec_type == "investigate_incident"
    reversible = bool(rollback_note)

    props: dict[str, Any] = {
        # An action is reversible only if it declares a rollback path.
        "action_reversible": reversible,
        # The simulated actions in this MVP never touch sensitive data or a DB.
        "sensitive_data_affected": False,
        "database_affected": False,
        # Security actions tighten network / access policy.
        "network_or_security_policy_modified": is_security,
        "changes_access_policy": is_security,
    }

    # A critical security finding in production is the canonical escalation case.
    if is_security and environment == "production" and (
        risk_level == "critical"
        or iss.get("severity") == "critical"
        or iss.get("issue_type") == "critical_exposed_vulnerability"
    ):
        props["critical_production_vulnerability"] = True

    # Performance incidents are investigated by humans, never auto-actioned.
    if is_incident:
        props["unknown_dependency"] = True

    return props


# --------------------------------------------------------------------------- #
# Evaluation (no execution)
# --------------------------------------------------------------------------- #
def evaluate(
    recommendation: Any,
    workload: Any | None = None,
    issue: Any | None = None,
    *,
    action_properties: dict[str, Any] | None = None,
) -> SafetyRoutingDecision:
    """Run the deterministic safety router for a recommendation (no execution).

    Powers ``POST /api/remediation/evaluate/{recId}``: it returns the chosen
    execution path and the full audit trail without performing any action.
    """
    props = action_properties
    if props is None:
        props = derive_action_properties(recommendation, workload, issue)
    context: RemediationContext = build_remediation_context(
        recommendation, workload, props
    )
    return route(context)


# --------------------------------------------------------------------------- #
# Escalation actions (Requirements 10.1, 10.2)
# --------------------------------------------------------------------------- #
def _run_escalation(
    rec: dict[str, Any],
    wl: dict[str, Any],
    iss: dict[str, Any],
    registry: ConnectorRegistry,
    routing: SafetyRoutingDecision | None = None,
) -> list[MCPToolExecution]:
    """Open a tracking ticket and notify the relevant teams for an escalation.

    Builds the human-escalation timeline: a ticket carrying full Issue /
    Recommendation / Workload context, an owner-team notification, — for
    security issues — a security-team notification, and a closing audit-trail
    entry that records the escalation with its policy-compliance note
    (Requirements 10.1, 10.2). Every connector invocation is recorded as an
    :class:`MCPToolExecution` via the shared :class:`ConnectorRegistry`, exactly
    as the runbook executor records cloud/audit tool calls.
    """
    workload_id = rec.get("workload_id") or wl.get("workload_id") or ""
    owner_team = wl.get("owner_team") or "owner_team"
    action_category = rec.get("action_category")
    is_security = (
        action_category == "security"
        or rec.get("recommendation_type") == "restrict_access"
        or iss.get("issue_category") == "security"
    )

    timeline: list[MCPToolExecution] = []

    # 1) Tracking ticket with full context (Requirement 10.1).
    ticket_execution = registry.execute(
        "create_ticket",
        workload_id=workload_id,
        title=(
            f"Human escalation: {rec.get('recommended_action') or 'remediation'}"
        ),
        priority=rec.get("risk_level") or "high",
        assignee=owner_team,
        issue_id=rec.get("issue_id"),
        recommendation_id=rec.get("recommendation_id"),
        issue_type=iss.get("issue_type"),
        environment=wl.get("environment"),
    )
    timeline.append(ticket_execution)

    # 2) Notify the workload owner team (Requirement 10.2).
    timeline.append(
        registry.execute(
            "notify_owner",
            owner_team=owner_team,
            workload_id=workload_id,
            message=(
                "A remediation requires expert review and has been escalated to "
                "your team."
            ),
        )
    )

    # 3) Security issues also page the security team (Requirement 10.2).
    if is_security:
        timeline.append(
            registry.execute(
                "notify_security_team",
                workload_id=workload_id,
                message=(
                    "A critical security remediation has been escalated for "
                    "expert review."
                ),
            )
        )

    # 4) Record the escalation in the audit trail with its policy-compliance
    #    note, reusing the same connector plumbing as every other MCP tool.
    ticket_id = ticket_execution.output.get("ticket_id")
    timeline.append(
        registry.execute(
            "write_audit_log",
            event_type="remediation_escalated",
            actor="self_healing_engine",
            workload_id=workload_id,
            issue_id=rec.get("issue_id"),
            recommendation_id=rec.get("recommendation_id"),
            new_status="escalated",
            details={
                "ticket_id": ticket_id,
                "policy_compliance": "compliant",
                "why_safe": routing.why_safe if routing is not None else None,
                "owner_team_notified": owner_team,
                "security_team_notified": is_security,
            },
        )
    )

    return timeline


# --------------------------------------------------------------------------- #
# Timeline / narrative helpers
# --------------------------------------------------------------------------- #
def _build_execution_timeline(
    executions: list[MCPToolExecution], *, start: datetime
) -> list[dict[str, Any]]:
    """Stamp wall-clock timestamps onto the ordered tool executions.

    Each step's ``started_at`` follows the previous step's simulated duration so
    the timeline reads as a coherent sequence for the UI.
    """
    timeline: list[dict[str, Any]] = []
    cursor = start
    for index, execution in enumerate(executions, start=1):
        started_at = cursor
        finished_at = started_at + timedelta(milliseconds=execution.duration_ms)
        timeline.append(
            {
                "step": index,
                "tool": execution.tool,
                "category": execution.category,
                "status": execution.status,
                "duration_ms": execution.duration_ms,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "output": execution.output,
            }
        )
        cursor = finished_at
    return timeline


def _build_ai_decision_steps(
    rec: dict[str, Any],
    iss: dict[str, Any],
    routing: SafetyRoutingDecision,
    result_path: str,
    *,
    start: datetime,
) -> list[dict[str, Any]]:
    """Produce the timestamped AI decision trail (Requirement 11.1)."""
    steps: list[dict[str, Any]] = []

    def _add(step: str, description: str, offset_ms: int) -> None:
        steps.append(
            {
                "step": step,
                "description": description,
                "timestamp": (start + timedelta(milliseconds=offset_ms)).isoformat(),
            }
        )

    issue_desc = iss.get("issue_type") or "issue"
    _add(
        "diagnose",
        f"Diagnosed issue '{issue_desc}' on workload "
        f"{rec.get('workload_id')}.",
        0,
    )
    _add(
        "select_runbook",
        f"Selected recommendation '{rec.get('recommendation_type')}' "
        f"({rec.get('action_category')}).",
        10,
    )
    _add(
        "safety_routing",
        "Deterministic safety router chose "
        f"'{routing.execution_path}': {routing.why_safe}",
        20,
    )
    _add(
        "execute",
        f"Proceeding via the {result_path} path.",
        30,
    )
    return steps


def _build_impact_result(rec: dict[str, Any], realised: bool) -> dict[str, Any]:
    """Build the before / after / simulated-savings impact block.

    ``realised`` reflects whether the fix actually ran (auto/approved) or whether
    the savings remain projected only (escalation / no action applied).
    """
    oif = rec.get("optimization_impact_forecast") or {}
    before = oif.get("forecast_without_action", {})
    after = oif.get("forecast_after_action", {})
    savings = oif.get("projected_savings", {})
    return {
        "before": before,
        "after": after,
        "simulated_savings": savings,
        "savings_realised": realised,
    }


def _user_facing_report(
    rec: dict[str, Any],
    wl: dict[str, Any],
    result_path: str,
    execution_status: str,
    verification_result: str,
    rollback_triggered: bool,
    mcp_tools: list[MCPToolExecution],
) -> str:
    """Compose a plain-language narrative of the remediation (Requirement 11.2)."""
    workload_name = wl.get("workload_name") or rec.get("workload_id") or "the workload"
    action = rec.get("recommended_action") or rec.get("recommendation_type") or "a fix"
    tool_names = ", ".join(t.tool for t in mcp_tools) or "no tools"

    if result_path == "human_escalation":
        return (
            f"Remediation for {workload_name} was escalated to a human expert "
            f"because the deterministic safety policy classified it as too risky "
            f"to apply automatically. A tracking ticket was opened and the "
            f"relevant teams were notified ({tool_names}). Recommended action: "
            f"{action}. No changes were applied to the workload."
        )

    path_label = "automatically" if result_path == "auto_fix" else "after approval"
    if execution_status == "completed":
        return (
            f"Remediation for {workload_name} completed {path_label}. "
            f"The engine applied: {action}. Tools executed: {tool_names}. "
            f"Post-fix verification {verification_result}; the workload returned "
            f"to a healthy state."
        )
    if execution_status == "escalated":
        return (
            f"Remediation for {workload_name} was attempted {path_label} but "
            f"post-fix verification {verification_result}. The engine "
            f"{'rolled back the change and ' if rollback_triggered else ''}"
            f"escalated the issue to a human expert. Tools executed: {tool_names}."
        )
    return (
        f"Remediation for {workload_name} ended with status '{execution_status}'. "
        f"Recommended action: {action}. Tools executed: {tool_names}."
    )


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
def generate_report(
    recommendation: Any,
    workload: Any | None = None,
    issue: Any | None = None,
    *,
    routing: SafetyRoutingDecision | None = None,
    action_properties: dict[str, Any] | None = None,
    registry: ConnectorRegistry | None = None,
    **execution_kwargs: Any,
) -> RemediationResult:
    """Route, execute (or escalate), and assemble a full :class:`RemediationResult`.

    This is the single entry point the remediation API's ``execute`` endpoint
    calls. It:

    1. runs the deterministic safety router (unless a ``routing`` decision is
       supplied),
    2. executes the appropriate path — runbook + verify + rollback for
       auto-fix / approved fixes, or ticket + notifications for escalations,
    3. assembles every field of the :class:`RemediationResult`, including the
       timeline, MCP executions, audit-compliance record and the plain-language
       narrative.

    ``execution_kwargs`` are forwarded to
    :func:`~backend.modules.self_healing.healer.run_auto_fix` (test injection:
    ``simulate_healthy``, ``failing_tools``, tiny ``*_budget_ms`` values, etc.).
    """
    rec = _as_dict(recommendation)
    wl = _as_dict(workload)
    iss = _as_dict(issue)

    props = action_properties
    if props is None:
        props = derive_action_properties(recommendation, workload, issue)

    if routing is None:
        context = build_remediation_context(recommendation, workload, props)
        routing = route(context)

    result_path = _ROUTER_PATH_TO_RESULT_PATH.get(
        routing.execution_path, "user_approved"
    )
    if registry is None:
        # Enable MCP activity logging on the production remediation path so every
        # connector invocation is recorded centrally (best-effort; never fatal).
        registry = ConnectorRegistry(log_invocations=True)

    start = datetime.now(timezone.utc)
    rollback_triggered = False
    verification_result = "skipped"
    action_taken: dict[str, Any] = {
        "recommended_action": rec.get("recommended_action"),
        "recommendation_type": rec.get("recommendation_type"),
        "action_category": rec.get("action_category"),
    }

    if result_path == "human_escalation":
        mcp_tools = _run_escalation(rec, wl, iss, registry, routing)
        execution_status = "escalated"
        reason_for_action = routing.why_safe
        savings_realised = False
        action_taken["escalated"] = True
    else:
        # auto_fix or user_approved -> execute the runbook with verify/rollback.
        execution = run_auto_fix(recommendation, registry=registry, **execution_kwargs)
        mcp_tools = list(execution.timeline)
        verification_result = execution.verification.result
        rollback_triggered = execution.rollback_triggered
        if execution.final_status == "completed":
            execution_status = "completed"
        elif execution.final_status == "escalated":
            execution_status = "escalated"
        else:
            execution_status = "failed"
        reason_for_action = execution.reason or routing.why_safe
        savings_realised = execution_status == "completed"
        action_taken["final_status"] = execution.final_status

    execution_timeline = _build_execution_timeline(mcp_tools, start=start)
    ai_decision_steps = _build_ai_decision_steps(
        rec, iss, routing, result_path, start=start
    )
    impact_result = _build_impact_result(rec, savings_realised)

    approval_type = _PATH_TO_APPROVAL_TYPE.get(result_path, "user_approved")
    persistent_data_modified = bool(
        props.get("database_affected") or props.get("sensitive_data_affected")
    )
    audit_compliance = AuditCompliance(
        approval_type=approval_type,  # type: ignore[arg-type]
        policy_compliance="compliant",
        rollback_available=routing.rollback_available,
        retention_expires=start + timedelta(days=_RETENTION_DAYS),
        persistent_data_modified=persistent_data_modified,
    )

    user_facing_report = _user_facing_report(
        rec,
        wl,
        result_path,
        execution_status,
        verification_result,
        rollback_triggered,
        mcp_tools,
    )

    result = RemediationResult(
        remediation_id=_new_remediation_id(),
        recommendation_id=rec.get("recommendation_id") or "",
        issue_id=rec.get("issue_id") or "",
        workload_id=rec.get("workload_id") or "",
        execution_path=result_path,  # type: ignore[arg-type]
        execution_status=execution_status,  # type: ignore[arg-type]
        action_taken=action_taken,
        reason_for_action=reason_for_action,
        safety_decision=routing.to_safety_decision(),
        ai_decision_steps=ai_decision_steps,
        mcp_tools_executed=mcp_tools,
        impact_result=impact_result,
        execution_timeline=execution_timeline,
        audit_compliance=audit_compliance,
        user_facing_report=user_facing_report,
        rollback_triggered=rollback_triggered,
        verification_result=verification_result,  # type: ignore[arg-type]
    )
    logger.info(
        "Generated remediation report %s (path=%s, status=%s) for rec %s",
        result.remediation_id,
        result.execution_path,
        result.execution_status,
        result.recommendation_id,
    )
    return result
