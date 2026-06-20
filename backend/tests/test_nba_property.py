"""Property-based tests for Module 2 (Next Best Action), task 4.5.

Exercises three correctness properties of the NBA engine, risk assessor, and
optimization-impact calculator using Hypothesis. These are pure, deterministic
components (no ML, no DB, no LLM), so each property is tested directly against
the module functions.

**Property 5: NBA Output and Rule Traceability**
    For any valid Issue whose ``issue_type`` is one of the 7 defined types
    (paired with a compatible workload context across all environments and
    criticalities), the NBA engine produces exactly ONE Recommendation / draft
    carrying a non-empty ``rule_triggered.rule_id`` and a non-empty
    ``rule_triggered.conditions_matched``.

**Property 6: Risk-to-Execution-Mode Consistency**
    For any (environment, reversibility, security/sensitivity,
    workflow_criticality, issue_severity, rule policy) context, the assigned
    ``risk_level`` matches the documented context->risk mapping and the
    ``required_execution_mode`` matches the risk->mode mapping (critical always
    routes to human_escalation_required, and the more-restrictive-of-policy rule
    is honoured).

**Property 7: Forecast Completeness and Arithmetic Consistency**
    For any non-negative baseline 30-day forecast and any of the 7 recommendation
    types, every component of the OptimizationImpactForecast is non-negative and
    ``forecast_without_action - forecast_after_action == projected_savings`` for
    each of cost / energy / carbon.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.4**

The reference mappings in Property 6 are encoded independently from the SDD-05
documented tables (see ``risk_assessor`` docstring) so the test is a genuine
consistency check between the documented specification and the implementation,
not a restatement of the code.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from backend.modules.next_best_action import nba_engine, risk_assessor
from backend.modules.next_best_action.optimization_impact import (
    compute_optimization_impact,
)
from backend.schemas.issue import (
    EstimatedImpact,
    Issue,
    MLResult,
    XAIExplanation,
    XAIFactor,
)
from backend.schemas.workload import Workload

# --------------------------------------------------------------------------- #
# Domain constants under test
# --------------------------------------------------------------------------- #
# The 7 issue types -> the rule each should match (by issue_type) and the
# issue_category the detector assigns. Mirrors recommendation_rules.json and the
# detection-rules table in design.md.
ISSUE_TYPE_TO_CONTEXT: dict[str, tuple[str, str]] = {
    # issue_type: (expected rule_id, issue_category)
    "critical_exposed_vulnerability": ("RULE-SEC-001", "security"),
    "public_storage": ("RULE-SEC-002", "security"),
    "idle_or_overprovisioned_workload": ("RULE-COST-ENERGY-001", "cost_energy_carbon"),
    "carbon_heavy_workload": ("RULE-CARBON-001", "carbon"),
    "high_error_rate": ("RULE-PERF-001", "performance"),
    "no_monitoring": ("RULE-MON-001", "monitoring"),
    "cost_spike_or_waste": ("RULE-COST-001", "cost"),
}

ENVIRONMENTS = ("production", "staging", "testing", "development")
CRITICALITIES = ("critical", "high", "medium", "low")
SEVERITIES = ("low", "medium", "high", "critical")
RECOMMENDATION_TYPES = (
    "shutdown_schedule",
    "resize_workload",
    "shutdown_and_resize",
    "reschedule_batch_job",
    "enable_monitoring",
    "restrict_access",
    "investigate_incident",
)
RISK_LEVELS = ("low", "medium", "high", "critical")
EXECUTION_MODES = (
    "auto_fix",
    "user_approval_required",
    "human_escalation_required",
)
# Realistic per-environment execution-mode policy baselines drawn from the rules.
EXECUTION_MODE_POLICIES = (
    {"production": "human_escalation_required", "non_production": "user_approval_required"},
    {"production": "user_approval_required", "non_production": "auto_fix"},
    {"production": "user_approval_required", "non_production": "user_approval_required"},
    {"production": "human_escalation_required", "non_production": "auto_fix"},
    {},  # missing policy -> defaults exercised
)


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _make_workload(environment: str, criticality: str) -> Workload:
    """Build a schema-valid Workload for the given environment + criticality."""
    return Workload(
        workload_id="wl-nba-prop-001",
        workload_name="NBA Prop Workload",
        workload_type="Service",
        cloud_service_type="vm",
        environment=environment,  # type: ignore[arg-type]
        region="us-east-1",
        owner_team="platform-team",
        construction_workflow="bim_model_data_processing",
        workflow_criticality=criticality,  # type: ignore[arg-type]
        status="warning",
    )


def _make_issue(issue_type: str, severity: str, risk_word: str = "low") -> Issue:
    """Build a schema-valid Issue of the given type and severity."""
    category = ISSUE_TYPE_TO_CONTEXT[issue_type][1]
    return Issue(
        issue_id="iss-nba-prop-001",
        workload_id="wl-nba-prop-001",
        issue_type=issue_type,
        issue_category=category,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        confidence_score=0.8,
        detected_evidence={"note": "synthetic property-test evidence"},
        ml_result=MLResult(
            model_name="fallback_rules_only", anomaly_score=-0.1, is_anomaly=True
        ),
        xai_explanation=XAIExplanation(
            method="rule-based feature contribution fallback",
            top_contributing_factors=[
                XAIFactor(feature="cpu_usage_percent", value=5.0, impact="low cpu"),
                XAIFactor(feature="runtime_hours_24h", value=23.0, impact="long runtime"),
                XAIFactor(feature="cost_30d_forecast", value=2000.0, impact="high cost"),
            ],
        ),
        llm_user_explanation="Synthetic explanation for property testing.",
        estimated_impact=EstimatedImpact(
            cost_risk=risk_word,  # type: ignore[arg-type]
            energy_risk=risk_word,  # type: ignore[arg-type]
            carbon_risk=risk_word,  # type: ignore[arg-type]
            security_risk=risk_word,  # type: ignore[arg-type]
            workflow_disruption_risk=risk_word,  # type: ignore[arg-type]
        ),
        status="new",
        detected_at=datetime.now(timezone.utc),
    )


# --------------------------------------------------------------------------- #
# Independent reference mappings for Property 6 (from SDD-05 documented tables)
# --------------------------------------------------------------------------- #
_MODE_ORDER = {mode: i for i, mode in enumerate(EXECUTION_MODES)}
_RISK_TO_MODE = {
    "low": "auto_fix",
    "medium": "user_approval_required",
    "high": "user_approval_required",
    "critical": "human_escalation_required",
}


def _expected_risk(
    *,
    environment: str,
    security: bool,
    issue_severity: str | None,
    reversible: bool,
    criticality: str,
) -> str:
    """Reference context->risk mapping (independent of the implementation)."""
    if environment == "production" and (security or issue_severity == "critical"):
        return "critical"
    if environment == "production":
        return "high"
    if environment == "staging":
        return "high" if criticality in {"high", "critical"} else "medium"
    # development / testing (true non-production)
    if criticality in {"high", "critical"}:
        return "medium"
    if reversible and criticality in {"low", "medium"}:
        return "low"
    if not reversible:
        return "medium"
    return "medium"


def _expected_mode(
    *, risk_level: str, policy: dict[str, str], environment: str
) -> str:
    """Reference risk+policy->mode mapping (independent of the implementation)."""
    if risk_level == "critical":
        return "human_escalation_required"
    if environment == "production":
        baseline = policy.get("production", "user_approval_required")
    else:
        baseline = policy.get("non_production", "user_approval_required")
    risk_mode = _RISK_TO_MODE[risk_level]
    # More restrictive of (baseline, risk_mode).
    return baseline if _MODE_ORDER[baseline] >= _MODE_ORDER[risk_mode] else risk_mode


# --------------------------------------------------------------------------- #
# Property 5 - NBA Output and Rule Traceability
# --------------------------------------------------------------------------- #
@settings(max_examples=50, deadline=None)
@given(
    issue_type=st.sampled_from(sorted(ISSUE_TYPE_TO_CONTEXT.keys())),
    environment=st.sampled_from(ENVIRONMENTS),
    criticality=st.sampled_from(CRITICALITIES),
    severity=st.sampled_from(SEVERITIES),
)
def test_property5_nba_output_and_rule_traceability(
    issue_type, environment, criticality, severity
):
    """Any valid Issue of a defined type yields exactly one traceable rec."""
    issue = _make_issue(issue_type, severity)
    workload = _make_workload(environment, criticality)
    expected_rule_id = ISSUE_TYPE_TO_CONTEXT[issue_type][0]

    # Exactly one draft is produced (single object, not None / not a list).
    draft = nba_engine.build_draft(issue, workload)
    assert draft is not None, f"no draft produced for issue_type={issue_type}"

    # Rule traceability: non-empty rule_id matching the expected rule, and a
    # non-empty conditions_matched (always includes the issue_type match).
    assert draft.rule_triggered.rule_id == expected_rule_id
    assert isinstance(draft.rule_triggered.rule_id, str)
    assert draft.rule_triggered.rule_id.strip()
    assert len(draft.rule_triggered.conditions_matched) >= 1
    assert all(c.strip() for c in draft.rule_triggered.conditions_matched)
    assert any("issue_type" in c for c in draft.rule_triggered.conditions_matched)

    # The full Recommendation carries the same traceability and valid enums.
    recommendation = nba_engine.recommend(issue, workload)
    assert recommendation is not None
    assert recommendation.rule_triggered.rule_id == expected_rule_id
    assert recommendation.rule_triggered.conditions_matched
    assert recommendation.risk_level in RISK_LEVELS
    assert recommendation.required_execution_mode in EXECUTION_MODES


# --------------------------------------------------------------------------- #
# Property 6 - Risk-to-Execution-Mode Consistency
# --------------------------------------------------------------------------- #
@settings(max_examples=50, deadline=None)
@given(
    environment=st.sampled_from(ENVIRONMENTS),
    reversible=st.booleans(),
    is_security=st.booleans(),
    criticality=st.sampled_from(CRITICALITIES),
    issue_severity=st.sampled_from(SEVERITIES),
    policy=st.sampled_from(EXECUTION_MODE_POLICIES),
    action_category=st.sampled_from(
        ["security", "cost", "carbon", "performance", "monitoring", "cost_energy_carbon"]
    ),
    recommendation_type=st.sampled_from(RECOMMENDATION_TYPES),
)
def test_property6_risk_to_execution_mode_consistency(
    environment,
    reversible,
    is_security,
    criticality,
    issue_severity,
    policy,
    action_category,
    recommendation_type,
):
    """risk_level matches context->risk; mode matches risk->mode (+policy)."""
    # security is true when explicitly flagged OR the action category is security.
    security = is_security or action_category == "security"

    risk_level, risk_reasons = risk_assessor.assess_risk(
        environment=environment,
        action_category=action_category,
        recommendation_type=recommendation_type,
        workflow_criticality=criticality,
        reversible=reversible,
        is_security=is_security,
        issue_severity=issue_severity,
    )
    expected_risk = _expected_risk(
        environment=environment,
        security=security,
        issue_severity=issue_severity,
        reversible=reversible,
        criticality=criticality,
    )
    assert risk_level == expected_risk, (
        f"risk mismatch: env={environment} security={security} "
        f"crit={criticality} reversible={reversible} sev={issue_severity} "
        f"-> got {risk_level}, expected {expected_risk}"
    )
    assert risk_level in RISK_LEVELS
    assert risk_reasons, "risk decision must carry an audit reason"

    mode, mode_reasons = risk_assessor.select_execution_mode(
        risk_level, policy, environment
    )
    expected_mode = _expected_mode(
        risk_level=risk_level, policy=policy, environment=environment
    )
    assert mode == expected_mode, (
        f"mode mismatch: risk={risk_level} env={environment} policy={policy} "
        f"-> got {mode}, expected {expected_mode}"
    )
    assert mode in EXECUTION_MODES
    assert mode_reasons

    # Critical risk always escalates, regardless of policy.
    if risk_level == "critical":
        assert mode == "human_escalation_required"

    # The combined assess() must agree with the two-step result, and
    # approval_required is consistent with the mode.
    assessment = risk_assessor.assess(
        environment=environment,
        action_category=action_category,
        recommendation_type=recommendation_type,
        workflow_criticality=criticality,
        reversible=reversible,
        execution_mode_policy=policy,
        is_security=is_security,
        issue_severity=issue_severity,
    )
    assert assessment.risk_level == risk_level
    assert assessment.required_execution_mode == mode
    assert assessment.approval_required == (mode != "auto_fix")


# --------------------------------------------------------------------------- #
# Property 7 - Forecast Completeness and Arithmetic Consistency
# --------------------------------------------------------------------------- #
def _nonneg():
    return st.floats(
        min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
    )


@settings(max_examples=50, deadline=None)
@given(
    cost_30d=_nonneg(),
    energy_kwh_30d=_nonneg(),
    carbon_kgco2e_30d=_nonneg(),
    recommendation_type=st.sampled_from(RECOMMENDATION_TYPES),
    range_point=st.sampled_from(["min", "mid", "max"]),
)
def test_property7_forecast_completeness_and_arithmetic(
    cost_30d, energy_kwh_30d, carbon_kgco2e_30d, recommendation_type, range_point
):
    """All forecast components are non-negative and without - after == savings."""
    forecast = compute_optimization_impact(
        cost_30d=cost_30d,
        energy_kwh_30d=energy_kwh_30d,
        carbon_kgco2e_30d=carbon_kgco2e_30d,
        recommendation_type=recommendation_type,
        range_point=range_point,  # type: ignore[arg-type]
    )

    without = forecast.forecast_without_action
    after = forecast.forecast_after_action
    savings = forecast.projected_savings

    # Completeness: every component present and non-negative for all 3 dims.
    for component in (without, after, savings):
        assert component.cost_30d >= 0.0
        assert component.energy_30d_kwh >= 0.0
        assert component.carbon_30d_kgco2e >= 0.0

    # Baseline (without) must equal the supplied inputs.
    assert without.cost_30d == cost_30d
    assert without.energy_30d_kwh == energy_kwh_30d
    assert without.carbon_30d_kgco2e == carbon_kgco2e_30d

    # Arithmetic consistency: without - after == savings (exact by construction).
    assert without.cost_30d - after.cost_30d == savings.cost_30d
    assert without.energy_30d_kwh - after.energy_30d_kwh == savings.energy_30d_kwh
    assert without.carbon_30d_kgco2e - after.carbon_30d_kgco2e == savings.carbon_30d_kgco2e

    # After-action never exceeds the baseline (savings are real reductions).
    assert after.cost_30d <= without.cost_30d
    assert after.energy_30d_kwh <= without.energy_30d_kwh
    assert after.carbon_30d_kgco2e <= without.carbon_30d_kgco2e
