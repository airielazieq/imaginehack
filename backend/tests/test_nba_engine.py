"""Tests for the rule-based Next Best Action engine + risk assessor (task 4.1).

Covers Requirements:
  - 5.1: an Issue maps to exactly one Recommendation with an action category/type.
  - 5.2: a risk level (low|medium|high|critical) is assigned from environment,
         reversibility, sensitive-data exposure, and workflow criticality.
  - 5.3: an execution mode (auto_fix|user_approval_required|
         human_escalation_required) is selected from the risk level + safety.
  - 5.4: the triggered rule id and matched conditions are recorded for audit.

The scenario-driven tests reuse the 7 demo payloads from
``mock_data/scenario_payloads.json`` (with workload context from
``sample_workloads.json``). Each scenario's ``expected_issue_type`` is the link
between detection (Module 1) and the NBA rules (Module 2): we synthesise an
Issue for that type and assert it maps to exactly one recommendation rule with a
risk-consistent execution mode.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from backend.core.config import MOCK_DATA_DIR
from backend.modules.next_best_action import (
    NBAEngine,
    RecommendationDraft,
    assess_risk,
    build_draft,
    match_rule,
    recommend,
    select_execution_mode,
)
from backend.schemas.issue import (
    EstimatedImpact,
    Issue,
    MLResult,
    XAIExplanation,
    XAIFactor,
)
from backend.schemas.recommendation import Recommendation
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload

_VALID_RISK = {"low", "medium", "high", "critical"}
_VALID_MODES = {"auto_fix", "user_approval_required", "human_escalation_required"}

# issue_type -> (expected rule_id, action_category, recommendation_type)
_EXPECTED_RULE = {
    "idle_or_overprovisioned_workload": (
        "RULE-COST-ENERGY-001",
        "cost_energy_carbon",
        "shutdown_and_resize",
    ),
    "critical_exposed_vulnerability": ("RULE-SEC-001", "security", "restrict_access"),
    "public_storage": ("RULE-SEC-002", "security", "restrict_access"),
    "carbon_heavy_workload": ("RULE-CARBON-001", "carbon", "reschedule_batch_job"),
    "no_monitoring": ("RULE-MON-001", "monitoring", "enable_monitoring"),
    "cost_spike_or_waste": ("RULE-COST-001", "cost", "resize_workload"),
    "high_error_rate": ("RULE-PERF-001", "performance", "investigate_incident"),
}

# issue_type -> issue_category (mirrors detection_rules categories).
_ISSUE_CATEGORY = {
    "idle_or_overprovisioned_workload": "cost_energy_carbon",
    "critical_exposed_vulnerability": "security",
    "public_storage": "security",
    "carbon_heavy_workload": "carbon",
    "no_monitoring": "monitoring",
    "cost_spike_or_waste": "cost",
    "high_error_rate": "performance",
}


# --- Loaders / fixtures ------------------------------------------------------
def _load_json(name: str):
    with (MOCK_DATA_DIR / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def workloads_by_id() -> dict[str, Workload]:
    raw = _load_json("sample_workloads.json")
    return {w["workload_id"]: Workload(**w) for w in raw}


@pytest.fixture(scope="module")
def scenarios() -> list[dict]:
    return _load_json("scenario_payloads.json")["scenarios"]


def _make_issue(scenario: dict, telemetry: TelemetrySnapshot) -> Issue:
    """Synthesise an Issue mirroring what Module 1 would emit for a scenario."""
    issue_type = scenario["expected_issue_type"]
    # detected_evidence carries the telemetry fields so the NBA rule conditions
    # can be evaluated even without a separate telemetry argument.
    return Issue(
        issue_id=f"iss-{scenario['scenario_id']}",
        workload_id=scenario["target_workload_id"],
        issue_type=issue_type,
        issue_category=_ISSUE_CATEGORY[issue_type],
        severity="high",
        confidence_score=0.9,
        detected_evidence=telemetry.model_dump(),
        ml_result=MLResult(
            model_name="Isolation Forest", anomaly_score=-0.5, is_anomaly=True
        ),
        xai_explanation=XAIExplanation(
            method="SHAP-style feature contribution",
            top_contributing_factors=[
                XAIFactor(feature="cpu_usage_percent", value=4.0, impact="low usage")
            ],
        ),
        llm_user_explanation="placeholder",
        estimated_impact=EstimatedImpact(
            cost_risk="medium",
            energy_risk="medium",
            carbon_risk="medium",
            security_risk="low",
            workflow_disruption_risk="low",
        ),
        status="new",
        detected_at=datetime.now(timezone.utc),
    )


# --- Scenario-driven: Issue -> exactly one Recommendation (Req 5.1, 5.4) -----
def test_each_scenario_maps_to_exactly_one_rule(scenarios, workloads_by_id):
    assert len(scenarios) == 7
    seen_rule_ids: set[str] = set()

    for scenario in scenarios:
        telemetry = TelemetrySnapshot(**scenario["telemetry"])
        workload = workloads_by_id[scenario["target_workload_id"]]
        issue = _make_issue(scenario, telemetry)

        match = match_rule(issue, workload=workload, telemetry=telemetry)
        assert match is not None, f"{scenario['scenario_id']} matched no rule"

        expected_rule, expected_cat, expected_type = _EXPECTED_RULE[issue.issue_type]
        assert match.rule_id == expected_rule
        assert match.action_category == expected_cat
        assert match.recommendation_type == expected_type
        # Req 5.4: rule id is non-empty and conditions are recorded for audit.
        assert match.rule_id
        assert match.conditions_matched, "conditions_matched must not be empty"
        assert match.conditions_matched[0].startswith("issue_type eq")
        seen_rule_ids.add(match.rule_id)

    # All 7 distinct rules fire across the 7 scenarios.
    assert len(seen_rule_ids) == 7


def test_each_scenario_produces_one_recommendation_object(scenarios, workloads_by_id):
    """Req 5.1: exactly one Recommendation per Issue, with valid risk + mode."""
    for scenario in scenarios:
        telemetry = TelemetrySnapshot(**scenario["telemetry"])
        workload = workloads_by_id[scenario["target_workload_id"]]
        issue = _make_issue(scenario, telemetry)

        rec = recommend(issue, workload, telemetry=telemetry)
        assert isinstance(rec, Recommendation)
        assert rec.issue_id == issue.issue_id
        assert rec.workload_id == issue.workload_id
        assert rec.rule_triggered.rule_id
        assert rec.rule_triggered.conditions_matched
        assert rec.risk_level in _VALID_RISK
        assert rec.required_execution_mode in _VALID_MODES
        # approval_required is consistent with the execution mode.
        assert rec.approval_required == (rec.required_execution_mode != "auto_fix")


# --- Scenario-driven: execution mode consistent with risk (Req 5.2, 5.3) -----
def test_execution_modes_consistent_with_risk_mapping(scenarios, workloads_by_id):
    by_workload = {}
    for scenario in scenarios:
        telemetry = TelemetrySnapshot(**scenario["telemetry"])
        workload = workloads_by_id[scenario["target_workload_id"]]
        issue = _make_issue(scenario, telemetry)
        draft = build_draft(issue, workload, telemetry=telemetry)
        assert draft is not None
        by_workload[scenario["expected_issue_type"]] = draft

        # Generic invariant: critical risk MUST escalate to a human.
        if draft.risk_level == "critical":
            assert draft.required_execution_mode == "human_escalation_required"
        # auto_fix is only ever chosen at low risk.
        if draft.required_execution_mode == "auto_fix":
            assert draft.risk_level == "low"

    # The two anchors called out by the task spec.
    # Critical production vulnerability -> human escalation.
    vuln = by_workload["critical_exposed_vulnerability"]
    assert vuln.risk_level == "critical"
    assert vuln.required_execution_mode == "human_escalation_required"

    # Idle dev server -> auto-fix (low risk, reversible, non-prod).
    idle = by_workload["idle_or_overprovisioned_workload"]
    assert idle.risk_level == "low"
    assert idle.required_execution_mode == "auto_fix"

    # Public storage in production (sensitive data) -> human escalation.
    storage = by_workload["public_storage"]
    assert storage.required_execution_mode == "human_escalation_required"

    # Production high-error-rate incident -> human escalation (per rule policy).
    perf = by_workload["high_error_rate"]
    assert perf.required_execution_mode == "human_escalation_required"

    # Carbon-heavy staging batch -> approval (risk escalates above auto_fix).
    carbon = by_workload["carbon_heavy_workload"]
    assert carbon.required_execution_mode == "user_approval_required"

    # Missing monitoring on a dev pipeline -> auto-fix.
    mon = by_workload["no_monitoring"]
    assert mon.required_execution_mode == "auto_fix"


# --- Unit: risk assessor -----------------------------------------------------
def test_assess_risk_production_security_is_critical():
    risk, reasons = assess_risk(
        environment="production",
        action_category="security",
        recommendation_type="restrict_access",
        workflow_criticality="high",
        reversible=True,
        is_security=True,
    )
    assert risk == "critical"
    assert reasons


def test_assess_risk_non_prod_reversible_low_is_low():
    risk, _ = assess_risk(
        environment="development",
        action_category="cost",
        recommendation_type="resize_workload",
        workflow_criticality="low",
        reversible=True,
    )
    assert risk == "low"


def test_assess_risk_staging_medium_is_medium():
    risk, _ = assess_risk(
        environment="staging",
        action_category="carbon",
        recommendation_type="reschedule_batch_job",
        workflow_criticality="medium",
        reversible=True,
    )
    assert risk == "medium"


def test_critical_risk_always_escalates_regardless_of_policy():
    # Even when the rule policy would only ask for approval, critical escalates.
    mode, _ = select_execution_mode(
        "critical",
        {"production": "user_approval_required", "non_production": "auto_fix"},
        "production",
    )
    assert mode == "human_escalation_required"


def test_select_execution_mode_takes_more_restrictive_of_risk_and_policy():
    # Risk medium (-> user_approval) vs policy auto_fix on non-prod -> approval.
    mode, _ = select_execution_mode(
        "medium",
        {"production": "user_approval_required", "non_production": "auto_fix"},
        "staging",
    )
    assert mode == "user_approval_required"

    # Low risk + policy auto_fix on non-prod -> auto_fix.
    mode, _ = select_execution_mode(
        "low",
        {"production": "user_approval_required", "non_production": "auto_fix"},
        "development",
    )
    assert mode == "auto_fix"


# --- Unit: matcher fallbacks -------------------------------------------------
def test_match_rule_returns_none_for_unknown_issue_type(workloads_by_id):
    workload = next(iter(workloads_by_id.values()))
    issue = Issue(
        issue_id="iss-unknown",
        workload_id=workload.workload_id,
        issue_type="totally_unknown_type",
        issue_category="cost",
        severity="low",
        confidence_score=0.5,
        detected_evidence={},
        ml_result=MLResult(model_name="x", anomaly_score=0.0, is_anomaly=False),
        xai_explanation=XAIExplanation(
            method="SHAP-style feature contribution", top_contributing_factors=[]
        ),
        llm_user_explanation="",
        estimated_impact=EstimatedImpact(
            cost_risk="low",
            energy_risk="low",
            carbon_risk="low",
            security_risk="low",
            workflow_disruption_risk="low",
        ),
        status="new",
        detected_at=datetime.now(timezone.utc),
    )
    assert match_rule(issue, workload=workload) is None
    assert recommend(issue, workload) is None


def test_engine_wrapper_matches_module_functions(scenarios, workloads_by_id):
    scenario = scenarios[0]
    telemetry = TelemetrySnapshot(**scenario["telemetry"])
    workload = workloads_by_id[scenario["target_workload_id"]]
    issue = _make_issue(scenario, telemetry)

    engine = NBAEngine()
    rec = engine.recommend(issue, workload, telemetry=telemetry)
    assert isinstance(rec, Recommendation)
    draft = engine.build_draft(issue, workload, telemetry=telemetry)
    assert isinstance(draft, RecommendationDraft)
    assert rec.rule_triggered.rule_id == draft.rule_triggered.rule_id
