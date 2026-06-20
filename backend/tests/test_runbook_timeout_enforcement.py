"""Tests for runbook verification/rollback timeout enforcement (task 21.2 —
Requirements 8.2, 8.3).

The design mandates hard time budgets for the self-healing phases:

* runbook execution within 120s → abort + log + escalate,
* verification within 30s → roll back,
* rollback within 60s → abort + log + escalate.

These tests exercise each timeout path **deterministically** by injecting tiny
``*_budget_ms`` budgets (the same injectable pattern the runbook tests use) so
no real waiting occurs, and they assert that:

* a timeout escalates with a rollback attempt,
* every timeout writes a ``remediation_timeout`` entry to the audit trail, and
* the happy path within budget still completes normally with no timeout audit
  noise.

A final test confirms the timeout outcome is surfaced consistently on the
``RemediationResult`` produced by the report generator.
"""

from __future__ import annotations

from backend.modules.self_healing import run_auto_fix
from backend.modules.self_healing.healer import execute_runbook
from backend.modules.self_healing import report_generator


# --------------------------------------------------------------------------- #
# Fixtures (plain dicts — no DB / pipeline needed)
# --------------------------------------------------------------------------- #
def _impact_forecast() -> dict:
    return {
        "forecast_without_action": {
            "cost_30d": 1000.0,
            "energy_30d_kwh": 500.0,
            "carbon_30d_kgco2e": 200.0,
        },
        "forecast_after_action": {
            "cost_30d": 600.0,
            "energy_30d_kwh": 300.0,
            "carbon_30d_kgco2e": 120.0,
        },
        "projected_savings": {
            "cost_30d": 400.0,
            "energy_30d_kwh": 200.0,
            "carbon_30d_kgco2e": 80.0,
        },
    }


def _auto_fix_recommendation() -> dict:
    """A non-prod, reversible recommendation eligible for the auto_fix path."""
    return {
        "recommendation_id": "rec-timeout-21-2",
        "issue_id": "iss-timeout-21-2",
        "workload_id": "wl-idle-dev-21-2",
        "recommended_action": "Stop the idle workload.",
        "action_category": "cost_optimization",
        "recommendation_type": "shutdown_and_resize",
        "risk_level": "low",
        "required_execution_mode": "auto_fix",
        "mcp_tools": ["stop", "scale"],
        "rollback_note": "Re-start the workload to restore the prior state.",
        "optimization_impact_forecast": _impact_forecast(),
    }


_AUTO_WORKLOAD = {
    "workload_id": "wl-idle-dev-21-2",
    "workload_name": "Idle Dev Server",
    "environment": "development",
    "workflow_criticality": "low",
    "owner_team": "devops-team",
}


def _timeout_audit_events(execution) -> list:
    """Return the timeout audit-trail entries recorded on an execution."""
    return [
        e
        for e in execution.audit_events
        if e.input.get("event_type") == "remediation_timeout"
    ]


# --------------------------------------------------------------------------- #
# Verification timeout -> rollback + escalate + audit log (Requirement 8.3)
# --------------------------------------------------------------------------- #
def test_verification_timeout_triggers_rollback_and_logs_audit():
    execution = run_auto_fix(_auto_fix_recommendation(), verification_budget_ms=1)

    # The runbook itself completed; only verification breached its budget.
    assert execution.runbook.succeeded
    assert execution.verification.timed_out is True
    assert execution.verification.result == "failed"

    # Timeout -> rollback + escalate.
    assert execution.timed_out_phase == "verification"
    assert execution.final_status == "escalated"
    assert execution.escalated is True
    assert execution.rollback_triggered is True
    assert execution.rollback is not None
    # The successful `stop` step is compensated by its inverse `start`.
    assert any(ex.tool == "start" for ex in execution.rollback.timeline)

    # The timeout is logged to the audit trail (Requirement 8.3: abort + log).
    audit_events = _timeout_audit_events(execution)
    assert len(audit_events) == 1
    audit = audit_events[0]
    assert audit.status == "success"
    assert audit.input["details"]["phase"] == "verification"
    assert audit.input["details"]["escalated"] is True
    assert audit.input["new_status"] == "escalated"
    assert audit.input["recommendation_id"] == "rec-timeout-21-2"
    # The audit entry is part of the merged execution timeline.
    assert audit in execution.timeline


# --------------------------------------------------------------------------- #
# Rollback timeout -> abort + escalate + audit log (Requirement 8.3)
# --------------------------------------------------------------------------- #
def test_rollback_timeout_aborts_escalates_and_logs_audit():
    # Force verification to fail (so a rollback runs) AND give rollback a 1ms
    # budget so the rollback itself times out.
    execution = run_auto_fix(
        _auto_fix_recommendation(),
        simulate_healthy=False,
        rollback_budget_ms=1,
    )

    assert execution.rollback is not None
    assert execution.rollback.timed_out is True
    assert execution.rollback.status == "timed_out"

    # A rollback timeout still escalates (abort + escalate) and keeps the
    # rollback escalation requirement.
    assert execution.timed_out_phase == "rollback"
    assert execution.final_status == "escalated"
    assert execution.escalated is True
    assert execution.rollback.escalation_required is True

    # The rollback timeout is logged to the audit trail.
    audit_events = _timeout_audit_events(execution)
    assert len(audit_events) == 1
    assert audit_events[0].input["details"]["phase"] == "rollback"
    assert audit_events[0].input["details"]["rollback_triggered"] is True


# --------------------------------------------------------------------------- #
# Runbook timeout -> abort + escalate + audit log (Requirement 8.2 timeout flow)
# --------------------------------------------------------------------------- #
def test_runbook_timeout_aborts_escalates_and_logs_audit():
    execution = run_auto_fix(_auto_fix_recommendation(), runbook_budget_ms=1)

    assert execution.runbook.timed_out is True
    assert execution.runbook.succeeded is False
    assert execution.timed_out_phase == "runbook"
    assert execution.final_status == "escalated"
    assert execution.rollback_triggered is True

    # The runbook timeout is logged exactly once as a runbook-phase timeout
    # (it must NOT be double-counted as a verification timeout).
    audit_events = _timeout_audit_events(execution)
    assert len(audit_events) == 1
    assert audit_events[0].input["details"]["phase"] == "runbook"


# --------------------------------------------------------------------------- #
# Happy path within budget -> completes normally, no timeout audit noise
# --------------------------------------------------------------------------- #
def test_happy_path_within_budget_completes_with_no_timeout_audit():
    execution = run_auto_fix(_auto_fix_recommendation())

    assert execution.final_status == "completed"
    assert execution.escalated is False
    assert execution.rollback_triggered is False
    assert execution.rollback is None
    assert execution.verification.passed
    assert execution.verification.timed_out is False
    # No phase breached its budget and nothing was written to the audit trail.
    assert execution.timed_out_phase is None
    assert execution.audit_events == []
    assert _timeout_audit_events(execution) == []
    # Timeline is exactly the two runbook steps (no rollback / audit entries).
    assert len(execution.timeline) == 2
    assert all(ex.status == "success" for ex in execution.timeline)


def test_execute_runbook_wrapper_surfaces_timeout_phase_and_audit_events():
    result = execute_runbook(
        _auto_fix_recommendation(),
        workload=_AUTO_WORKLOAD,
        verification_budget_ms=1,
    )

    assert result["final_status"] == "escalated"
    assert result["timed_out_phase"] == "verification"
    assert result["rollback_triggered"] is True
    assert result["verification_result"] == "failed"
    # The timeout audit entry is exposed in the structured dict.
    assert any(
        e["input"]["event_type"] == "remediation_timeout"
        for e in result["audit_events"]
    )


# --------------------------------------------------------------------------- #
# RemediationResult surfaces the timeout consistently (Requirement 8.4)
# --------------------------------------------------------------------------- #
def test_remediation_result_records_timeout_outcome():
    result = report_generator.generate_report(
        _auto_fix_recommendation(),
        _AUTO_WORKLOAD,
        {"issue_type": "idle_resource"},
        verification_budget_ms=1,
    ).model_dump(mode="json")

    # The remediation is escalated with a rollback and a failed verification.
    assert result["execution_path"] == "auto_fix"
    assert result["execution_status"] == "escalated"
    assert result["rollback_triggered"] is True
    assert result["verification_result"] == "failed"

    # The timeout audit entry is present in the executed-tools timeline so the
    # report carries a full, auditable record of the breach.
    tools = {t["tool"]: t for t in result["mcp_tools_executed"]}
    assert "write_audit_log" in tools
    assert tools["write_audit_log"]["output"]["event_type"] == "remediation_timeout"
    # The execution timeline and the MCP tools list stay aligned.
    assert len(result["execution_timeline"]) == len(result["mcp_tools_executed"])
