"""Composed auto-fix execution path for Module 3 — task 5.3.

Wires the three primitives built in this task into the guardrailed auto-fix
sequence (Requirements 8.1-8.3)::

    execute runbook  ->  verify  ->  (on failure) rollback  ->  escalate

This is the clean entry point the report generator (task 5.5) and the
remediation API call. It returns a single structured :class:`SelfHealingExecution`
carrying the execution timeline, the verification outcome and the rollback
status — everything 5.5 needs to assemble a full ``RemediationResult`` — but it
deliberately does **not** build the ``RemediationResult`` or persist anything.

All timing is simulated and deterministic (no real 30s/60s sleeps), so this
runs instantly in tests and demos.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.connectors import ConnectorRegistry
from backend.modules.self_healing.rollback import (
    RollbackOutcome,
    rollback,
    rollback_budget_ms as _default_rollback_budget_ms,
)
from backend.modules.self_healing.runbook_executor import (
    RunbookExecutionResult,
    RunbookExecutor,
    RunbookStep,
    build_runbook,
)
from backend.modules.self_healing.verification import (
    HealthProbe,
    VerificationOutcome,
    verify,
    verification_budget_ms as _default_verification_budget_ms,
)
from backend.schemas.remediation import MCPToolExecution

logger = logging.getLogger("clover.self_healing.healer")


def _audit_timeout(
    registry: ConnectorRegistry,
    phase: str,
    *,
    workload_id: str | None,
    issue_id: str | None,
    recommendation_id: str | None,
    budget_ms: int,
    elapsed_ms: int,
    rollback_triggered: bool,
    escalated: bool,
) -> MCPToolExecution:
    """Write a timeout event to the audit trail (Requirements 8.2, 8.3).

    The design mandates "abort + log + escalate" for runbook/verification/rollback
    timeouts. This records the breach as a ``write_audit_log`` MCP execution
    through the shared registry — the same connector plumbing every other MCP
    tool uses — so the timeout is visible in both the audit trail and the
    remediation timeline. Deterministic and side-effect free (the simulated
    audit connector does not persist unless explicitly configured to).
    """
    return registry.execute(
        "write_audit_log",
        event_type="remediation_timeout",
        actor="self_healing_engine",
        workload_id=workload_id or "",
        issue_id=issue_id,
        recommendation_id=recommendation_id,
        new_status="escalated" if escalated else "failed",
        details={
            "phase": phase,
            "budget_ms": budget_ms,
            "elapsed_ms": elapsed_ms,
            "rollback_triggered": rollback_triggered,
            "escalated": escalated,
            "policy_compliance": "compliant",
            "message": (
                f"The {phase} phase exceeded its {budget_ms}ms time budget "
                f"(elapsed {elapsed_ms}ms); aborting and "
                f"{'escalating to a human expert' if escalated else 'failing'}."
            ),
        },
    )


class SelfHealingExecution(BaseModel):
    """Structured outcome of the composed auto-fix path.

    Provides everything the report generator (5.5) needs without prescribing
    the final ``RemediationResult`` shape.
    """

    workload_id: str | None
    recommendation_id: str | None
    final_status: str  # "completed" | "escalated" | "failed"
    escalated: bool
    rollback_triggered: bool
    runbook: RunbookExecutionResult
    verification: VerificationOutcome
    rollback: RollbackOutcome | None = None
    # Convenience: the merged execution timeline (runbook + any rollback steps +
    # any timeout audit-trail entries).
    timeline: list = Field(default_factory=list)
    # Which phase (if any) breached its time budget: "runbook" | "verification" |
    # "rollback" | None.
    timed_out_phase: str | None = None
    # Audit-trail entries written for timeout events (Requirement 8.2/8.3:
    # "abort + log + escalate"). Each is a recorded ``write_audit_log`` execution.
    audit_events: list = Field(default_factory=list)
    total_duration_ms: int = 0
    reason: str = ""


def run_auto_fix(
    recommendation: Any,
    *,
    registry: ConnectorRegistry | None = None,
    steps: list[RunbookStep] | None = None,
    health_probe: HealthProbe | None = None,
    simulate_healthy: bool | None = None,
    failing_tools: set[str] | None = None,
    runbook_budget_ms: int | None = None,
    verification_budget_ms: int | None = None,
    rollback_budget_ms: int | None = None,
    audit_timeouts: bool = True,
) -> SelfHealingExecution:
    """Execute the guardrailed auto-fix sequence for a recommendation.

    The safety router (task 5.1) is responsible for deciding *whether* a
    recommendation may take the auto-fix path; this function assumes that
    decision has already been made and performs the execution.

    Args:
        recommendation: the Recommendation (or mapping) whose ``mcp_tools`` form
            the runbook. Its ``rollback_note`` drives compensation.
        registry: shared connector registry (one is created if omitted so the
            runbook and any rollback act on the same simulated connectors).
        steps: optional explicit runbook steps; defaults to
            :func:`build_runbook` over the recommendation's ``mcp_tools``.
        health_probe / simulate_healthy: control the verification outcome (see
            :func:`verify`).
        failing_tools: tool names to force-fail in the runbook (test injection).
        *_budget_ms: optional tiny budgets to exercise timeout paths fast.

    Returns:
        A :class:`SelfHealingExecution`.
    """
    rec = _as_dict(recommendation)
    workload_id = rec.get("workload_id")
    recommendation_id = rec.get("recommendation_id")
    issue_id = rec.get("issue_id")
    rollback_note = rec.get("rollback_note")

    if registry is None:
        registry = ConnectorRegistry()
    if steps is None:
        steps = build_runbook(recommendation)

    # Resolve the effective budgets for each phase so timeout audit entries can
    # report the exact threshold that was breached.
    effective_verification_budget = (
        verification_budget_ms
        if verification_budget_ms is not None
        else _default_verification_budget_ms()
    )
    effective_rollback_budget = (
        rollback_budget_ms
        if rollback_budget_ms is not None
        else _default_rollback_budget_ms()
    )

    audit_events: list[MCPToolExecution] = []
    timed_out_phase: str | None = None

    # 1) Execute the runbook (hard budget: runbook_timeout_seconds, default 120s).
    executor = RunbookExecutor(registry, budget_ms=runbook_budget_ms)
    runbook_result = executor.execute(steps, failing_tools=failing_tools)

    # 1a) Runbook timeout -> abort + log + escalate (Requirement 8.2 timeout flow).
    if runbook_result.timed_out:
        timed_out_phase = "runbook"
        if audit_timeouts:
            audit_events.append(
                _audit_timeout(
                    registry,
                    "runbook",
                    workload_id=workload_id,
                    issue_id=issue_id,
                    recommendation_id=recommendation_id,
                    budget_ms=executor.budget_ms,
                    elapsed_ms=runbook_result.total_duration_ms,
                    rollback_triggered=True,
                    escalated=True,
                )
            )

    # 2) Verify the fix (hard budget: verification_timeout_seconds, default 30s).
    verification = verify(
        workload_id,
        runbook_result,
        health_probe=health_probe,
        simulate_healthy=simulate_healthy,
        budget_ms=verification_budget_ms,
    )

    # 2a) Verification timeout -> treat as failure + log + roll back (Req 8.3).
    #     Only attribute the timeout to verification when the runbook itself
    #     completed; a runbook timeout propagates into the verification outcome
    #     but is already recorded above as a runbook timeout.
    if runbook_result.succeeded and verification.timed_out:
        timed_out_phase = "verification"
        if audit_timeouts:
            audit_events.append(
                _audit_timeout(
                    registry,
                    "verification",
                    workload_id=workload_id,
                    issue_id=issue_id,
                    recommendation_id=recommendation_id,
                    budget_ms=effective_verification_budget,
                    elapsed_ms=verification.duration_ms,
                    rollback_triggered=True,
                    escalated=True,
                )
            )

    timeline = list(runbook_result.timeline)
    total_duration = runbook_result.total_duration_ms + verification.duration_ms

    # 3) On verification pass -> completed. On failure -> rollback + escalate.
    if verification.passed:
        return SelfHealingExecution(
            workload_id=workload_id,
            recommendation_id=recommendation_id,
            final_status="completed",
            escalated=False,
            rollback_triggered=False,
            runbook=runbook_result,
            verification=verification,
            rollback=None,
            timeline=timeline,
            timed_out_phase=None,
            audit_events=[],
            total_duration_ms=total_duration,
            reason="Auto-fix succeeded and verification passed.",
        )

    rollback_outcome = rollback(
        runbook_result.timeline,
        rollback_note=rollback_note,
        workload_id=workload_id,
        registry=registry,
        budget_ms=rollback_budget_ms,
    )

    # 3a) Rollback timeout -> abort + log + escalate (Requirement 8.3 timeout flow).
    if rollback_outcome.timed_out:
        timed_out_phase = "rollback"
        if audit_timeouts:
            audit_events.append(
                _audit_timeout(
                    registry,
                    "rollback",
                    workload_id=workload_id,
                    issue_id=issue_id,
                    recommendation_id=recommendation_id,
                    budget_ms=effective_rollback_budget,
                    elapsed_ms=rollback_outcome.total_duration_ms,
                    rollback_triggered=True,
                    escalated=True,
                )
            )

    timeline = timeline + list(rollback_outcome.timeline) + list(audit_events)
    total_duration += rollback_outcome.total_duration_ms

    reason = _escalation_reason(timed_out_phase, rollback_outcome)
    return SelfHealingExecution(
        workload_id=workload_id,
        recommendation_id=recommendation_id,
        final_status="escalated",
        escalated=True,
        rollback_triggered=True,
        runbook=runbook_result,
        verification=verification,
        rollback=rollback_outcome,
        timeline=timeline,
        timed_out_phase=timed_out_phase,
        audit_events=audit_events,
        total_duration_ms=total_duration,
        reason=reason,
    )


def _escalation_reason(
    timed_out_phase: str | None, rollback_outcome: RollbackOutcome
) -> str:
    """Compose the human-readable escalation reason, noting any timeout breach."""
    if timed_out_phase == "runbook":
        return (
            "Runbook execution exceeded its time budget; aborted, "
            f"rollback {rollback_outcome.status}, and escalating to a human expert."
        )
    if timed_out_phase == "verification":
        return (
            "Verification exceeded its time budget; "
            f"rollback {rollback_outcome.status}, and escalating to a human expert."
        )
    if timed_out_phase == "rollback":
        return (
            "Verification failed after auto-fix and the rollback then exceeded "
            "its time budget; aborting rollback and escalating to a human expert."
        )
    return (
        "Verification failed after auto-fix; "
        f"rollback {rollback_outcome.status}; escalating to a human expert."
    )


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    raise TypeError(f"Cannot read a recommendation from {type(obj)!r}")


def execute_runbook(
    recommendation: Any,
    workload: Any | None = None,
    *,
    registry: ConnectorRegistry | None = None,
    steps: list[RunbookStep] | None = None,
    health_probe: HealthProbe | None = None,
    simulate_healthy: bool | None = None,
    failing_tools: set[str] | None = None,
    runbook_budget_ms: int | None = None,
    verification_budget_ms: int | None = None,
    rollback_budget_ms: int | None = None,
    audit_timeouts: bool = True,
) -> dict[str, Any]:
    """Orchestrate the full self-healing sequence and return plain structured data.

    This is the consumption-friendly wrapper around :func:`run_auto_fix` for the
    report generator (task 5.5) and the remediation API. It runs::

        build runbook -> execute steps -> verify -> (rollback if failed) -> escalate

    and returns a JSON-serializable ``dict`` carrying the execution timeline, the
    verification outcome and the rollback outcome. It deliberately does **not**
    assemble a ``RemediationResult`` or persist anything — that is task 5.5.

    Args:
        recommendation: the Recommendation (or mapping). Its ``mcp_tools`` (or,
            failing that, its ``recommendation_type`` via :func:`build_runbook`)
            define the runbook; its ``rollback_note`` drives compensation.
        workload: optional Workload (or mapping); used to surface workload
            context in the returned data. Routing/safety remains the safety
            router's responsibility (task 5.1).
        Remaining keyword args mirror :func:`run_auto_fix` (test injection +
            tiny budgets to exercise timeout paths quickly).

    Returns:
        A ``dict`` with keys: ``workload_id``, ``workload_name``,
        ``recommendation_id``, ``recommendation_type``, ``final_status``,
        ``escalated``, ``rollback_triggered``, ``verification_result``
        (``passed`` | ``failed`` | ``skipped``), ``runbook``, ``verification``,
        ``rollback`` (or ``None``), ``execution_timeline`` (list of step dicts),
        ``total_duration_ms`` and ``reason``.
    """
    execution = run_auto_fix(
        recommendation,
        registry=registry,
        steps=steps,
        health_probe=health_probe,
        simulate_healthy=simulate_healthy,
        failing_tools=failing_tools,
        runbook_budget_ms=runbook_budget_ms,
        verification_budget_ms=verification_budget_ms,
        rollback_budget_ms=rollback_budget_ms,
        audit_timeouts=audit_timeouts,
    )

    rec = _as_dict(recommendation)
    wl = _as_dict(workload)

    return {
        "workload_id": execution.workload_id,
        "workload_name": wl.get("workload_name"),
        "recommendation_id": execution.recommendation_id,
        "recommendation_type": rec.get("recommendation_type"),
        "final_status": execution.final_status,
        "escalated": execution.escalated,
        "rollback_triggered": execution.rollback_triggered,
        "verification_result": execution.verification.result,
        "timed_out_phase": execution.timed_out_phase,
        "runbook": execution.runbook.model_dump(),
        "verification": execution.verification.model_dump(),
        "rollback": (
            execution.rollback.model_dump() if execution.rollback else None
        ),
        "execution_timeline": [step.model_dump() for step in execution.timeline],
        "audit_events": [event.model_dump() for event in execution.audit_events],
        "total_duration_ms": execution.total_duration_ms,
        "reason": execution.reason,
    }
