"""Rule-based Next Best Action engine for Module 2.

This component answers *what the team should do* about a detected
:class:`~backend.schemas.issue.Issue`. It is deterministic, explainable, and
safe: the recommendation rules in ``rules/recommendation_rules.json`` are
authoritative and the LLM (added later) only ever explains the chosen action.

Pipeline (this task, 4.1):

    Issue + Workload -> rule match (by issue_type, optionally telemetry)
                     -> risk level + execution mode (risk_assessor)
                     -> RecommendationDraft

A ``RecommendationDraft`` carries every deterministic field of a
:class:`~backend.schemas.recommendation.Recommendation` *except* the forecast.
The XGBoost forecaster (task 4.2) and Optimization Impact calculator (task 4.3)
produce the forecast pieces; task 4.4 composes them via
:func:`assemble_recommendation`. For standalone use and testing,
:func:`recommend` assembles a full ``Recommendation`` using a clearly-labelled
neutral placeholder forecast (``model_name="pending_forecast"``) that the later
tasks replace.

Rule matching: each rule's ``match.issue_types`` is unique across the policy,
so an Issue maps to **exactly one** rule by ``issue_type``. The rule's
telemetry ``conditions`` are evaluated as *optional* reinforcement against a
context merged from (telemetry, the Issue's ``detected_evidence``, the
Workload) and recorded in ``conditions_matched`` for audit traceability.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.core.config import load_policy
from backend.modules.next_best_action import risk_assessor
from backend.schemas.issue import Issue
from backend.schemas.recommendation import (
    ForecastComponent,
    ForecastModelResult,
    OptimizationImpactForecast,
    Recommendation,
    RuleTriggered,
)
from backend.schemas.workload import Workload

logger = logging.getLogger("clover.nba.engine")

_NUMERIC_OPERATORS = {"lt", "lte", "gt", "gte"}
_SUPPORTED_OPERATORS = {"eq", "neq", "in"} | _NUMERIC_OPERATORS


# --- Rule matching -----------------------------------------------------------
@dataclass
class RecommendationRuleMatch:
    """A recommendation rule that matched an Issue.

    Attributes:
        rule_id: The recommendation rule identifier (e.g. ``RULE-SEC-001``).
        action_category: The rule's action category.
        recommendation_type: The rule's recommendation type.
        recommended_action: Human-readable recommended action text.
        conditions_matched: Audit-friendly descriptions of the satisfied match
            criteria (always includes the ``issue_type`` match).
        mcp_tools: MCP tool names the action would invoke.
        rollback_note: How to revert the action (``None`` when not applicable).
        execution_mode_policy: The rule's per-environment baseline mode policy.
        rule: The raw rule dict (kept for downstream tasks, e.g. optimisation
            factors used by task 4.3).
    """

    rule_id: str
    action_category: str
    recommendation_type: str
    recommended_action: str
    conditions_matched: list[str]
    mcp_tools: list[str]
    rollback_note: str | None
    execution_mode_policy: dict[str, str]
    rule: dict[str, Any] = field(default_factory=dict)


def _to_plain(obj: Any) -> dict[str, Any]:
    """Return a plain dict for a Pydantic model, mapping, or generic object."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    raise TypeError(f"Cannot build a field context from {type(obj)!r}")


def _build_context(
    issue: Issue,
    workload: Any | None,
    telemetry: Any | None,
) -> dict[str, Any]:
    """Merge workload, the Issue's detected_evidence, and telemetry into one map.

    Precedence (lowest to highest): workload < detected_evidence < telemetry.
    Telemetry, when supplied, is the freshest signal and wins on collisions.
    """
    context: dict[str, Any] = {}
    context.update(_to_plain(workload))
    evidence = issue.detected_evidence if isinstance(issue.detected_evidence, dict) else {}
    context.update(evidence)
    if telemetry is not None:
        context.update(_to_plain(telemetry))
    return context


def _compare(operator: str, actual: Any, expected: Any) -> bool:
    """Apply a single comparison operator; return False on type mismatch."""
    if operator == "eq":
        return actual == expected
    if operator == "neq":
        return actual != expected
    if operator == "in":
        try:
            return actual in expected
        except TypeError:
            return False
    # Numeric operators: guard against booleans and non-numerics.
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return False
    try:
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
    except TypeError:
        return False
    raise ValueError(f"Unsupported operator: {operator!r}")


def _matched_conditions(match_block: dict[str, Any], context: dict[str, Any]) -> list[str]:
    """Describe each telemetry condition that is satisfied by the context."""
    descriptions: list[str] = []
    for condition in match_block.get("conditions", []):
        field_name = condition.get("field")
        operator = condition.get("operator")
        expected = condition.get("value")
        if operator not in _SUPPORTED_OPERATORS:
            raise ValueError(f"Unsupported operator: {operator!r}")
        if field_name not in context:
            continue
        actual = context[field_name]
        if _compare(operator, actual, expected):
            descriptions.append(
                f"{field_name} {operator} {expected!r} (actual={actual!r})"
            )
    return descriptions


def match_rule(
    issue: Issue,
    *,
    workload: Any | None = None,
    telemetry: Any | None = None,
    policy: dict[str, Any] | None = None,
) -> RecommendationRuleMatch | None:
    """Match an Issue to exactly one recommendation rule by ``issue_type``.

    Args:
        issue: The detected Issue to recommend an action for.
        workload: The associated Workload (or mapping) for context.
        telemetry: Optional fresh TelemetrySnapshot (or mapping) used to
            evaluate the rule's telemetry conditions.
        policy: Optional pre-loaded recommendation policy; defaults to the
            cached ``recommendation_rules.json``.

    Returns:
        The matching :class:`RecommendationRuleMatch`, or ``None`` when no rule
        covers the issue type.
    """
    if policy is None:
        policy = load_policy("recommendation_rules")

    context = _build_context(issue, workload, telemetry)

    for rule in policy.get("rules", []):
        match_block = rule.get("match", {})
        issue_types = match_block.get("issue_types", [])
        if issue.issue_type not in issue_types:
            continue

        # issue_type is authoritative; telemetry conditions are reinforcement.
        conditions_matched = [
            f"issue_type eq {issue.issue_type!r}",
            *_matched_conditions(match_block, context),
        ]
        logger.debug(
            "Issue %s (%s) matched rule %s",
            issue.issue_id,
            issue.issue_type,
            rule["rule_id"],
        )
        return RecommendationRuleMatch(
            rule_id=rule["rule_id"],
            action_category=rule["action_category"],
            recommendation_type=rule["recommendation_type"],
            recommended_action=rule["recommended_action"],
            conditions_matched=conditions_matched,
            mcp_tools=list(rule.get("mcp_tools", [])),
            rollback_note=rule.get("rollback_note"),
            execution_mode_policy=dict(rule.get("execution_mode_policy", {})),
            rule=rule,
        )

    logger.warning(
        "No recommendation rule matched issue %s of type %s",
        issue.issue_id,
        issue.issue_type,
    )
    return None


# --- Recommendation draft (deterministic core) -------------------------------
@dataclass
class RecommendationDraft:
    """Deterministic recommendation core, sans forecast.

    Holds every rule-based and risk-based field of a ``Recommendation``. The
    forecast (tasks 4.2/4.3) is added separately via
    :func:`assemble_recommendation`.
    """

    issue_id: str
    workload_id: str
    recommended_action: str
    action_category: str
    recommendation_type: str
    rule_triggered: RuleTriggered
    risk_level: str
    required_execution_mode: str
    approval_required: bool
    mcp_tools: list[str]
    rollback_note: str | None
    risk_reasons: list[str] = field(default_factory=list)


def _is_reversible(rule_match: RecommendationRuleMatch) -> bool:
    """A rule's action is reversible when it declares a rollback note."""
    return rule_match.rollback_note is not None


def _resolve_workload_attrs(
    issue: Issue, workload: Any | None
) -> tuple[str | None, str | None]:
    """Extract (environment, workflow_criticality) from the workload context."""
    wl = _to_plain(workload)
    return wl.get("environment"), wl.get("workflow_criticality")


def build_draft(
    issue: Issue,
    workload: Any | None = None,
    *,
    telemetry: Any | None = None,
    policy: dict[str, Any] | None = None,
) -> RecommendationDraft | None:
    """Build the deterministic recommendation draft for an Issue.

    Returns ``None`` when no recommendation rule covers the issue type.
    """
    rule_match = match_rule(
        issue, workload=workload, telemetry=telemetry, policy=policy
    )
    if rule_match is None:
        return None

    environment, workflow_criticality = _resolve_workload_attrs(issue, workload)
    reversible = _is_reversible(rule_match)
    is_security = (
        rule_match.action_category == "security"
        or issue.issue_category == "security"
    )

    assessment = risk_assessor.assess(
        environment=environment,
        action_category=rule_match.action_category,
        recommendation_type=rule_match.recommendation_type,
        workflow_criticality=workflow_criticality,
        reversible=reversible,
        execution_mode_policy=rule_match.execution_mode_policy,
        is_security=is_security,
        issue_severity=issue.severity,
    )

    return RecommendationDraft(
        issue_id=issue.issue_id,
        workload_id=issue.workload_id,
        recommended_action=rule_match.recommended_action,
        action_category=rule_match.action_category,
        recommendation_type=rule_match.recommendation_type,
        rule_triggered=RuleTriggered(
            rule_id=rule_match.rule_id,
            conditions_matched=rule_match.conditions_matched,
        ),
        risk_level=assessment.risk_level,
        required_execution_mode=assessment.required_execution_mode,
        approval_required=assessment.approval_required,
        mcp_tools=rule_match.mcp_tools,
        rollback_note=rule_match.rollback_note,
        risk_reasons=assessment.reasons,
    )


# --- Full Recommendation assembly --------------------------------------------
def _neutral_forecast() -> tuple[ForecastModelResult, OptimizationImpactForecast]:
    """Return a clearly-labelled placeholder forecast.

    Tasks 4.2 (XGBoost forecaster) and 4.3 (Optimization Impact calculator)
    replace this. It is *not* a forecast computation, merely a schema-valid stub
    so the engine can emit a complete ``Recommendation`` standalone.
    """
    zero_component = ForecastComponent(
        cost_30d=0.0, energy_30d_kwh=0.0, carbon_30d_kgco2e=0.0
    )
    model_result = ForecastModelResult(
        model_name="pending_forecast",
        predicted_cost_30d=0.0,
        predicted_energy_kwh_30d=0.0,
        predicted_carbon_kgco2e_30d=0.0,
    )
    impact = OptimizationImpactForecast(
        forecast_without_action=zero_component,
        forecast_after_action=zero_component,
        projected_savings=zero_component,
    )
    return model_result, impact


def _default_explanation(draft: RecommendationDraft) -> str:
    """Template recommendation explanation (LLM wording is added later)."""
    return (
        f"Recommended action: {draft.recommended_action} "
        f"(risk: {draft.risk_level}, execution: {draft.required_execution_mode})."
    )


def assemble_recommendation(
    draft: RecommendationDraft,
    *,
    forecast_model_result: ForecastModelResult,
    optimization_impact_forecast: OptimizationImpactForecast,
    recommendation_id: str | None = None,
    llm_recommendation_explanation: str | None = None,
    created_at: datetime | None = None,
) -> Recommendation:
    """Compose a full :class:`Recommendation` from a draft and a forecast.

    Task 4.4 calls this with the real forecast pieces from tasks 4.2/4.3.
    """
    return Recommendation(
        recommendation_id=recommendation_id or f"rec-{uuid.uuid4().hex[:12]}",
        issue_id=draft.issue_id,
        workload_id=draft.workload_id,
        recommended_action=draft.recommended_action,
        action_category=draft.action_category,
        recommendation_type=draft.recommendation_type,
        rule_triggered=draft.rule_triggered,
        forecast_model_result=forecast_model_result,
        optimization_impact_forecast=optimization_impact_forecast,
        risk_level=draft.risk_level,
        required_execution_mode=draft.required_execution_mode,
        approval_required=draft.approval_required,
        mcp_tools=draft.mcp_tools,
        llm_recommendation_explanation=(
            llm_recommendation_explanation
            if llm_recommendation_explanation is not None
            else _default_explanation(draft)
        ),
        rollback_note=draft.rollback_note,
        created_at=created_at or datetime.now(timezone.utc),
    )


def recommend(
    issue: Issue,
    workload: Any | None = None,
    *,
    telemetry: Any | None = None,
    policy: dict[str, Any] | None = None,
    forecast_model_result: ForecastModelResult | None = None,
    optimization_impact_forecast: OptimizationImpactForecast | None = None,
) -> Recommendation | None:
    """Produce exactly one :class:`Recommendation` for an Issue.

    When ``forecast_model_result`` / ``optimization_impact_forecast`` are not
    supplied, a neutral placeholder forecast is used (replaced by tasks
    4.2/4.3 once wired in 4.4). Returns ``None`` when no rule matches.
    """
    draft = build_draft(issue, workload, telemetry=telemetry, policy=policy)
    if draft is None:
        return None

    if forecast_model_result is None or optimization_impact_forecast is None:
        default_model, default_impact = _neutral_forecast()
        forecast_model_result = forecast_model_result or default_model
        optimization_impact_forecast = optimization_impact_forecast or default_impact

    return assemble_recommendation(
        draft,
        forecast_model_result=forecast_model_result,
        optimization_impact_forecast=optimization_impact_forecast,
    )


# --- Thin engine wrapper (composed by task 4.4) ------------------------------
class NBAEngine:
    """Rule-based Next Best Action engine (Module 2 interface).

    A thin, stateless wrapper around the module-level functions, matching the
    ``NBAEngine`` protocol in the design. The forecaster (4.2) and optimisation
    calculator (4.3) are injected by task 4.4.
    """

    def __init__(self, policy: dict[str, Any] | None = None) -> None:
        self._policy = policy

    def recommend(
        self,
        issue: Issue,
        workload: Any | None = None,
        *,
        telemetry: Any | None = None,
        forecast_model_result: ForecastModelResult | None = None,
        optimization_impact_forecast: OptimizationImpactForecast | None = None,
    ) -> Recommendation | None:
        """Map an Issue to exactly one Recommendation (see :func:`recommend`)."""
        return recommend(
            issue,
            workload,
            telemetry=telemetry,
            policy=self._policy,
            forecast_model_result=forecast_model_result,
            optimization_impact_forecast=optimization_impact_forecast,
        )

    def build_draft(
        self,
        issue: Issue,
        workload: Any | None = None,
        *,
        telemetry: Any | None = None,
    ) -> RecommendationDraft | None:
        """Build only the deterministic draft (no forecast)."""
        return build_draft(issue, workload, telemetry=telemetry, policy=self._policy)
