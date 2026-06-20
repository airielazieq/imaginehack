"""Tests for the runbook executor, verification, rollback and composed auto-fix
path (task 5.3 — Requirements 8.1, 8.2, 8.3).

The simulated connectors are deterministic and never sleep, so these tests run
instantly. Timeout paths are exercised by configuring tiny budgets rather than
waiting real seconds.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.connectors import ConnectorRegistry
from backend.modules.self_healing import (
    RunbookExecutor,
    RunbookStep,
    build_runbook,
    execute_runbook,
    rollback,
    run_auto_fix,
    runbook_steps_for_recommendation_type,
    runbook_tools_by_type,
    verify,
)
from backend.modules.self_healing.runbook_executor import RunbookExecutionResult
from backend.schemas.recommendation import (
    ForecastComponent,
    ForecastModelResult,
    OptimizationImpactForecast,
    Recommendation,
    RuleTriggered,
)


# --- Fixtures / helpers ------------------------------------------------------
def make_recommendation(
    *,
    mcp_tools: list[str],
    workload_id: str = "wl-idle-dev-001",
    rollback_note: str | None = "Re-start the workload to restore prior state.",
) -> Recommendation:
    """Build a minimal-but-valid Recommendation for a non-prod auto-fix."""
    zero = ForecastComponent(cost_30d=0.0, energy_30d_kwh=0.0, carbon_30d_kgco2e=0.0)
    return Recommendation(
        recommendation_id="rec-001",
        issue_id="iss-001",
        workload_id=workload_id,
        recommended_action="Schedule idle shutdown and resize",
        action_category="cost_optimization",
        recommendation_type="shutdown_and_resize",
        rule_triggered=RuleTriggered(
            rule_id="RULE-COST-ENERGY-001", conditions_matched=["cpu<10", "runtime>=20"]
        ),
        forecast_model_result=ForecastModelResult(
            model_name="deterministic_forecast_fallback",
            predicted_cost_30d=100.0,
            predicted_energy_kwh_30d=50.0,
            predicted_carbon_kgco2e_30d=20.0,
        ),
        optimization_impact_forecast=OptimizationImpactForecast(
            forecast_without_action=zero,
            forecast_after_action=zero,
            projected_savings=zero,
        ),
        risk_level="low",
        required_execution_mode="auto_fix",
        approval_required=False,
        mcp_tools=mcp_tools,
        llm_recommendation_explanation="Idle dev server can be safely shut down.",
        rollback_note=rollback_note,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def registry() -> ConnectorRegistry:
    return ConnectorRegistry()


# --- build_runbook -----------------------------------------------------------
def test_build_runbook_maps_tools_and_threads_workload_id():
    rec = make_recommendation(mcp_tools=["schedule_shutdown", "resize_resource"])
    steps = build_runbook(rec)
    assert [s.tool for s in steps] == ["schedule_shutdown", "resize_resource"]
    assert all(s.params.get("workload_id") == "wl-idle-dev-001" for s in steps)


# --- Successful runbook + passing verification (Req 8.1, 8.2) ----------------
def test_successful_runbook_produces_all_success_timeline(registry):
    steps = build_runbook(
        make_recommendation(mcp_tools=["schedule_shutdown", "resize_resource"])
    )
    result = RunbookExecutor(registry).execute(steps)

    assert result.status == "success"
    assert result.succeeded
    assert len(result.timeline) == 2
    assert all(ex.status == "success" for ex in result.timeline)
    assert result.steps_succeeded == 2
    assert result.failed_tool is None


def test_verification_passes_after_successful_runbook(registry):
    steps = build_runbook(make_recommendation(mcp_tools=["schedule_shutdown"]))
    result = RunbookExecutor(registry).execute(steps)
    outcome = verify("wl-idle-dev-001", result)

    assert outcome.passed
    assert outcome.result == "passed"
    assert outcome.healthy is True
    assert outcome.checks  # non-empty list of checks


def test_run_auto_fix_happy_path_completes_without_rollback():
    rec = make_recommendation(mcp_tools=["schedule_shutdown", "resize_resource"])
    execution = run_auto_fix(rec)

    assert execution.final_status == "completed"
    assert execution.escalated is False
    assert execution.rollback_triggered is False
    assert execution.rollback is None
    assert execution.verification.passed
    assert len(execution.timeline) == 2
    assert all(ex.status == "success" for ex in execution.timeline)


# --- Failed step -> short-circuit -> rollback + escalate (Req 8.3) -----------
def test_failed_step_short_circuits_remaining_steps(registry):
    steps = build_runbook(
        make_recommendation(
            mcp_tools=["schedule_shutdown", "resize_resource", "enable_monitoring"]
        )
    )
    result = RunbookExecutor(registry).execute(
        steps, failing_tools={"resize_resource"}
    )

    assert result.status == "failed"
    assert result.failed_tool == "resize_resource"
    # First step ran, second failed, third skipped (short-circuit).
    assert [ex.status for ex in result.timeline] == ["success", "failed", "skipped"]
    assert len(result.timeline) == 3  # timeline stays complete


def test_run_auto_fix_runbook_failure_triggers_rollback_and_escalation():
    rec = make_recommendation(mcp_tools=["stop", "resize_resource"])
    execution = run_auto_fix(rec, failing_tools={"resize_resource"})

    assert execution.final_status == "escalated"
    assert execution.escalated is True
    assert execution.rollback_triggered is True
    assert execution.rollback is not None
    assert execution.rollback.escalation_required is True
    # The successful `stop` step must be compensated by its inverse `start`.
    rollback_tools = [ex.tool for ex in execution.rollback.timeline]
    assert "start" in rollback_tools


# --- Verification failure -> rollback + escalate (Req 8.3) -------------------
def test_run_auto_fix_verification_failure_triggers_rollback_and_escalation():
    rec = make_recommendation(mcp_tools=["stop"])
    execution = run_auto_fix(rec, simulate_healthy=False)

    assert execution.runbook.succeeded  # runbook itself was fine
    assert execution.verification.result == "failed"
    assert execution.final_status == "escalated"
    assert execution.rollback_triggered is True
    assert execution.rollback.status in {"completed", "partial"}
    # `stop` compensated by `start`.
    assert any(ex.tool == "start" for ex in execution.rollback.timeline)


def test_rollback_carries_rollback_note_and_marks_escalation():
    steps = build_runbook(make_recommendation(mcp_tools=["stop"]))
    runbook_result = RunbookExecutor().execute(steps)
    outcome = rollback(
        runbook_result.timeline,
        rollback_note="restore prior state",
        workload_id="wl-idle-dev-001",
    )

    assert outcome.escalation_required is True
    assert outcome.rollback_note == "restore prior state"
    assert outcome.compensating_actions >= 1


# --- Timeout simulation (Req 8.2, 8.3) ---------------------------------------
def test_runbook_timeout_is_represented_with_tiny_budget(registry):
    steps = build_runbook(
        make_recommendation(mcp_tools=["schedule_shutdown", "resize_resource"])
    )
    # A 1ms budget is exceeded by the very first simulated tool.
    result = RunbookExecutor(registry, budget_ms=1).execute(steps)

    assert result.timed_out is True
    assert result.status == "timed_out"
    assert any(
        ex.output.get("error") == "runbook_timeout" for ex in result.timeline
    )


def test_verification_timeout_is_represented_with_tiny_budget(registry):
    steps = build_runbook(make_recommendation(mcp_tools=["schedule_shutdown"]))
    result = RunbookExecutor(registry).execute(steps)
    outcome = verify("wl-idle-dev-001", result, budget_ms=1)

    assert outcome.timed_out is True
    assert outcome.result == "failed"


def test_rollback_timeout_is_represented_with_tiny_budget():
    steps = build_runbook(make_recommendation(mcp_tools=["stop", "scale"]))
    runbook_result = RunbookExecutor().execute(steps)
    outcome = rollback(
        runbook_result.timeline,
        rollback_note="restore",
        workload_id="wl-idle-dev-001",
        budget_ms=1,
    )

    assert outcome.timed_out is True
    assert outcome.status == "timed_out"
    assert outcome.escalation_required is True


def test_run_auto_fix_verification_timeout_escalates():
    rec = make_recommendation(mcp_tools=["stop"])
    execution = run_auto_fix(rec, verification_budget_ms=1)

    assert execution.verification.timed_out is True
    assert execution.final_status == "escalated"
    assert execution.rollback_triggered is True


# --- Determinism -------------------------------------------------------------
def test_runbook_execution_is_deterministic():
    steps = build_runbook(
        make_recommendation(mcp_tools=["schedule_shutdown", "resize_resource"])
    )
    a = RunbookExecutor(ConnectorRegistry()).execute(steps)
    b = RunbookExecutor(ConnectorRegistry()).execute(steps)

    assert isinstance(a, RunbookExecutionResult)
    assert a.total_duration_ms == b.total_duration_ms
    assert [e.tool for e in a.timeline] == [e.tool for e in b.timeline]
    assert [e.duration_ms for e in a.timeline] == [e.duration_ms for e in b.timeline]


# --- recommendation_type -> ordered tool steps (from recommendation_rules) ---
def test_runbook_tools_by_type_maps_known_recommendation_types():
    mapping = runbook_tools_by_type()
    # Derived directly from recommendation_rules.json mcp_tools.
    assert mapping["shutdown_and_resize"] == ["schedule_shutdown", "resize_resource"]
    assert mapping["enable_monitoring"] == ["enable_monitoring", "create_ticket"]
    assert mapping["reschedule_batch_job"] == [
        "reschedule_batch_job",
        "resize_resource",
    ]


def test_runbook_steps_for_known_and_unknown_type():
    assert runbook_steps_for_recommendation_type("resize_workload") == [
        "resize_resource",
        "notify_owner",
    ]
    # Unknown type yields an empty (no-op) runbook rather than raising.
    assert runbook_steps_for_recommendation_type("does_not_exist") == []


def test_build_runbook_falls_back_to_recommendation_type_mapping():
    # No explicit mcp_tools: steps are derived from recommendation_type.
    rec = make_recommendation(mcp_tools=[])
    rec.recommendation_type = "shutdown_and_resize"
    steps = build_runbook(rec)
    assert [s.tool for s in steps] == ["schedule_shutdown", "resize_resource"]
    assert all(s.params.get("workload_id") == "wl-idle-dev-001" for s in steps)


# --- execute_runbook orchestration (returns plain structured dict) -----------
def test_execute_runbook_happy_path_returns_structured_dict():
    rec = make_recommendation(mcp_tools=["schedule_shutdown", "resize_resource"])
    result = execute_runbook(rec, workload={"workload_name": "Idle Dev Server"})

    assert isinstance(result, dict)
    assert result["final_status"] == "completed"
    assert result["escalated"] is False
    assert result["rollback_triggered"] is False
    assert result["rollback"] is None
    assert result["verification_result"] == "passed"
    assert result["recommendation_type"] == "shutdown_and_resize"
    assert result["workload_name"] == "Idle Dev Server"
    assert len(result["execution_timeline"]) == 2
    assert all(step["status"] == "success" for step in result["execution_timeline"])


def test_execute_runbook_verification_failure_returns_rollback_and_escalation():
    rec = make_recommendation(mcp_tools=["stop"])
    result = execute_runbook(rec, simulate_healthy=False)

    assert result["final_status"] == "escalated"
    assert result["escalated"] is True
    assert result["rollback_triggered"] is True
    assert result["verification_result"] == "failed"
    assert result["rollback"] is not None
    assert result["rollback"]["escalation_required"] is True
    rollback_tools = [ex["tool"] for ex in result["rollback"]["timeline"]]
    assert "start" in rollback_tools


def test_execute_runbook_timeout_escalates():
    rec = make_recommendation(mcp_tools=["schedule_shutdown", "resize_resource"])
    result = execute_runbook(rec, runbook_budget_ms=1)

    assert result["runbook"]["timed_out"] is True
    assert result["final_status"] == "escalated"
    assert result["rollback_triggered"] is True
