"""Tests for the Module 3 safety router (task 5.1).

Covers Requirement 7 (Safety Rules and Execution Path Routing):
  - 7.1 auto_fix permitted ONLY when ALL seven auto-fix conditions hold
  - 7.2 any unmet auto-fix condition -> approval or escalation by risk
  - 7.3 routing is deterministic (rules only, no randomness)
  - 7.4 risk_level critical -> ALWAYS human_escalation_required

The router is driven by ``backend/rules/safety_rules.json`` (loaded via
``load_policy``). These tests build :class:`RemediationContext` objects directly
so each safety fact is explicit. They are example-based unit tests covering the
core routing branches and edge cases.
"""

from __future__ import annotations

import json

from backend.core.config import MOCK_DATA_DIR
from backend.modules.self_healing import (
    RemediationContext,
    build_remediation_context,
    route,
)
from backend.schemas.remediation import SafetyDecision

_PATHS = {"auto_fix", "user_approval_required", "human_escalation_required"}


def _auto_fix_eligible(**overrides) -> RemediationContext:
    """A context that satisfies ALL seven auto-fix conditions.

    non-production, reversible, no sensitive data, no DB, no net/sec policy
    change, criticality low/medium, rollback_note present. risk_level low and no
    escalation/approval facts set, so the router must choose ``auto_fix`` unless
    an override breaks one of the conditions.
    """
    base = {
        "environment": "development",
        "workflow_criticality": "low",
        "risk_level": "low",
        "ai_confidence": 0.95,
        "action": "schedule_shutdown",
        "action_reversible": True,
        "sensitive_data_affected": False,
        "database_affected": False,
        "network_or_security_policy_modified": False,
        "rollback_note": "Re-enable the schedule to restore the workload.",
    }
    base.update(overrides)
    return RemediationContext(**base)


# --- (a) all seven auto-fix conditions met -> auto_fix -----------------------
def test_all_conditions_met_routes_to_auto_fix():
    decision = route(_auto_fix_eligible())
    assert decision.execution_path == "auto_fix"
    assert decision.approval_required is False
    assert decision.rollback_available is True
    assert decision.blocklisted is False
    # The seven auto-fix condition ids should be reported as matched.
    assert len(decision.matched_conditions) == 7


# --- (b) any single auto-fix condition violated -> NOT auto_fix --------------
def test_each_auto_fix_condition_violation_blocks_auto_fix():
    violations = [
        {"environment": "production"},                       # -> approval
        {"action_reversible": False},                        # -> escalation
        {"sensitive_data_affected": True},                   # -> escalation
        {"database_affected": True},                         # -> not auto (approval default)
        {"network_or_security_policy_modified": True},       # -> not auto (approval default)
        {"workflow_criticality": "high"},                    # -> approval
        {"rollback_note": None},                             # -> not auto (approval default)
    ]
    for override in violations:
        decision = route(_auto_fix_eligible(**override))
        assert decision.execution_path != "auto_fix", (
            f"override {override} should disqualify auto_fix, "
            f"got {decision.execution_path}"
        )
        assert decision.execution_path in _PATHS


def test_database_affected_alone_falls_through_to_user_approval():
    # database_affected breaks an auto-fix condition but is not itself an
    # escalation/approval trigger -> default user_approval_required.
    decision = route(_auto_fix_eligible(database_affected=True))
    assert decision.execution_path == "user_approval_required"


# --- (c) escalation conditions (incl. critical risk) -------------------------
def test_critical_risk_always_escalates():
    # Even with an otherwise fully auto-fix-eligible context.
    decision = route(_auto_fix_eligible(risk_level="critical"))
    assert decision.execution_path == "human_escalation_required"
    assert "risk_level_critical" in decision.matched_conditions


def test_each_escalation_condition_routes_to_escalation():
    escalations = [
        {"critical_production_vulnerability": True},
        {"sensitive_data_affected": True},
        {"production_database_affected": True},
        {"unknown_dependency": True},
        {"may_cause_major_downtime": True},
        {"action_reversible": False},          # irreversible_action
        {"deletes_data": True},
        {"critical_network_or_security_policy": True},
        {"ai_confidence": 0.4},                # low_ai_confidence (< 0.5)
        {"risk_level": "critical"},
    ]
    for override in escalations:
        decision = route(_auto_fix_eligible(**override))
        assert decision.execution_path == "human_escalation_required", (
            f"override {override} should escalate, got {decision.execution_path}"
        )
        assert decision.approval_required is True


def test_low_ai_confidence_boundary():
    # 0.5 is NOT < 0.5 -> no escalation from confidence alone.
    assert route(_auto_fix_eligible(ai_confidence=0.5)).execution_path == "auto_fix"
    assert (
        route(_auto_fix_eligible(ai_confidence=0.49)).execution_path
        == "human_escalation_required"
    )


# --- (d) determinism ---------------------------------------------------------
def test_determinism_same_input_same_decision():
    ctx = _auto_fix_eligible(environment="staging", workflow_criticality="medium")
    first = route(ctx)
    second = route(RemediationContext(**ctx.model_dump()))
    assert first.model_dump() == second.model_dump()


def test_determinism_across_representative_contexts():
    """Identical inputs always produce an identical decision, across the full
    range of routing branches (auto_fix, approval, escalation, blocklist)."""
    cases = [
        _auto_fix_eligible(),                                  # auto_fix
        _auto_fix_eligible(environment="production"),          # approval
        _auto_fix_eligible(risk_level="critical"),             # escalation (risk)
        _auto_fix_eligible(action="delete_data"),              # escalation (blocklist)
        _auto_fix_eligible(database_affected=True),            # default approval
        _auto_fix_eligible(workflow_criticality="high"),       # approval
    ]
    for ctx in cases:
        d1 = route(ctx)
        d2 = route(RemediationContext(**ctx.model_dump()))
        # Identical inputs -> identical decision.
        assert d1.model_dump() == d2.model_dump()
        # Always a valid path.
        assert d1.execution_path in _PATHS


# --- (e) blocklisted actions always escalate ---------------------------------
def test_blocklisted_action_always_escalates():
    blocked = [
        "delete_data",
        "modify_production_database",
        "patch_critical_production_system",
        "change_production_security_policy",
        "change_production_network_policy",
        "irreversible_infrastructure_change",
        "act_under_unknown_dependency",
        "act_under_low_confidence",
    ]
    for action in blocked:
        # Even with an otherwise auto-fix-eligible context, the blocklist wins.
        decision = route(_auto_fix_eligible(action=action))
        assert decision.execution_path == "human_escalation_required", (
            f"blocked action {action} must escalate"
        )
        assert decision.blocklisted is True
        assert decision.blocklisted_action == action


def test_blocklist_matches_via_action_keywords():
    decision = route(
        _auto_fix_eligible(action="some_wrapper", action_keywords=["delete_data"])
    )
    assert decision.execution_path == "human_escalation_required"
    assert decision.blocklisted is True


# --- SafetyDecision projection ----------------------------------------------
def test_to_safety_decision_projection():
    decision = route(_auto_fix_eligible())
    sd = decision.to_safety_decision()
    assert isinstance(sd, SafetyDecision)
    assert sd.approval_required is False
    assert sd.rollback_available is True
    assert sd.why_safe  # non-empty rationale

    escalated = route(_auto_fix_eligible(risk_level="critical"))
    assert escalated.to_safety_decision().approval_required is True


# --- audit trail completeness ------------------------------------------------
def test_evaluated_conditions_audit_trail_present():
    decision = route(_auto_fix_eligible(environment="production"))
    audit = decision.evaluated_conditions
    assert set(audit) == {
        "blocklist",
        "escalation_conditions",
        "approval_conditions",
        "auto_fix_conditions",
    }
    # All seven auto-fix conditions are recorded even when the path isn't auto.
    assert len(audit["auto_fix_conditions"]) == 7
    # The production environment is recorded as a matched approval condition.
    approval_matched = [r for r in audit["approval_conditions"] if r["matched"]]
    assert any(r["id"] == "staging_or_production" for r in approval_matched)


# --- build_remediation_context helper ---------------------------------------
def test_build_remediation_context_from_objects():
    workload = {"environment": "development", "workflow_criticality": "low"}
    recommendation = {
        "risk_level": "low",
        "rollback_note": "scale back up",
        "recommendation_type": "schedule_shutdown",
        "action_category": "infrastructure",
        "recommended_action": "Schedule overnight shutdown",
    }
    action_properties = {
        "action_reversible": True,
        "sensitive_data_affected": False,
        "database_affected": False,
        "network_or_security_policy_modified": False,
    }
    ctx = build_remediation_context(recommendation, workload, action_properties)
    assert ctx.environment == "development"
    assert ctx.workflow_criticality == "low"
    assert ctx.risk_level == "low"
    assert ctx.rollback_note == "scale back up"
    assert ctx.action == "schedule_shutdown"

    decision = route(ctx)
    assert decision.execution_path == "auto_fix"


# --- alignment with the 7 demo scenarios' expected_execution_path ------------
def _scenarios() -> list[dict]:
    with (MOCK_DATA_DIR / "scenario_payloads.json").open("r", encoding="utf-8") as fh:
        return json.load(fh)["scenarios"]


def test_demo_scenarios_expected_paths():
    """Hand-built safety contexts reflecting each demo scenario's intent route
    to the scenario's documented ``expected_execution_path``.

    The raw scenario telemetry doesn't carry action-level safety facts (those
    come from the NBA / runbook layers), so we encode the safety context that
    each scenario is engineered to produce and check the router agrees with the
    spec's intended path.
    """
    contexts: dict[str, RemediationContext] = {
        # Idle dev server: non-prod, reversible shutdown, low criticality.
        "trigger_idle_dev_server": _auto_fix_eligible(),
        # Critical prod vulnerability: never auto-patch production.
        "trigger_critical_production_vulnerability": RemediationContext(
            environment="production",
            workflow_criticality="critical",
            risk_level="critical",
            critical_production_vulnerability=True,
            action="patch_critical_production_system",
            rollback_note=None,
        ),
        # Public storage in production: sensitive data exposure -> escalate.
        "trigger_public_storage_exposure": RemediationContext(
            environment="production",
            workflow_criticality="high",
            risk_level="high",
            sensitive_data_affected=True,
            changes_access_policy=True,
            action="update_storage_acl",
        ),
        # Carbon-heavy batch: reschedule, reversible, but reporting workflow in a
        # shared env needs approval.
        "trigger_carbon_heavy_batch_job": RemediationContext(
            environment="staging",
            workflow_criticality="medium",
            risk_level="medium",
            action_reversible=True,
            action="reschedule_batch_job",
            rollback_note="reschedule to original window",
        ),
        # Missing monitoring in a non-prod pipeline: safe to auto-enable.
        "trigger_missing_monitoring": _auto_fix_eligible(action="enable_monitoring"),
        # Cost spike on a testing VM: resize needs approval (config change).
        "trigger_cost_spike": RemediationContext(
            environment="testing",
            workflow_criticality="medium",
            risk_level="medium",
            action_reversible=True,
            modifies_config=True,
            action="resize_resource",
            rollback_note="resize back to original",
        ),
        # High error rate on a production dashboard: prod incident -> escalate.
        "trigger_high_error_rate": RemediationContext(
            environment="production",
            workflow_criticality="high",
            risk_level="high",
            may_cause_major_downtime=True,
            action="rolling_restart",
        ),
    }

    by_id = {s["scenario_id"]: s for s in _scenarios()}
    for scenario_id, ctx in contexts.items():
        expected = by_id[scenario_id]["expected_execution_path"]
        actual = route(ctx).execution_path
        assert actual == expected, (
            f"{scenario_id}: expected {expected}, got {actual}"
        )
