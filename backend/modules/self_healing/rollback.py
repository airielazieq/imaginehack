"""Rollback handler for Module 3 (Guardrailed Self-Healing) — task 5.3.

When post-fix verification fails, the engine must undo what it did and hand the
issue to a human (Requirement 8.3): trigger a **rollback within 60 seconds**,
then **escalate** to ``human_escalation_required``.

This module builds compensating MCP actions from the runbook timeline and the
recommendation's ``rollback_note``, executing them in **reverse order** through
the simulated connectors. As with the rest of Module 3 the timing is *simulated*
(no real sleeps): the connectors' deterministic ``duration_ms`` is accumulated
and compared against the rollback budget (``rollback_timeout_seconds`` from
``safety_rules.json``, overridable for fast tests).

Inverse mapping
---------------
Cloud actions that have a natural inverse tool are reversed directly
(``stop`` <-> ``start``, ``schedule_shutdown`` -> ``start`` ...). Actions
without a connector-level inverse (e.g. ``enable_monitoring``) are recorded as
``skipped`` compensating steps annotated with the ``rollback_note`` so the
timeline documents that a manual/no-op compensation applies. This keeps the
rollback timeline complete and auditable without inventing connector tools.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.connectors import ConnectorRegistry
from backend.core.config import load_policy
from backend.schemas.remediation import MCPToolExecution

logger = logging.getLogger("clover.self_healing.rollback")

# Fallback budget if the policy file omits the timer (seconds).
_DEFAULT_ROLLBACK_TIMEOUT_SECONDS = 60

# Maps a forward cloud tool to its compensating inverse tool. Tools absent from
# this map have no connector-level inverse and are recorded as skipped
# compensating steps (driven by the rollback_note).
INVERSE_TOOL_MAP: dict[str, str] = {
    "stop": "start",
    "start": "stop",
    "schedule_shutdown": "start",
    "scale": "scale",
    "resize_resource": "resize_resource",
    "update_storage_acl": "update_storage_acl",
    "reschedule_batch_job": "reschedule_batch_job",
    "restrict_public_access": "restrict_public_access",
}

# Tools that change nothing reversible (notifications, tickets, audit, restarts)
# are never compensated — they are informational or idempotent.
_NON_COMPENSATABLE_PREFIXES = ("notify_", "create_", "update_ticket", "assign_ticket")
_NON_COMPENSATABLE_TOOLS = {"write_audit_log", "restart", "restart_container"}


def rollback_budget_ms(policy: dict[str, Any] | None = None) -> int:
    """Return the rollback execution budget in milliseconds from policy timers."""
    if policy is None:
        policy = load_policy("safety_rules")
    timers = policy.get("timers", {}) if isinstance(policy, dict) else {}
    seconds = timers.get("rollback_timeout_seconds", _DEFAULT_ROLLBACK_TIMEOUT_SECONDS)
    return int(seconds * 1000)


class RollbackOutcome(BaseModel):
    """Result of a rollback attempt."""

    status: str  # "completed" | "partial" | "timed_out" | "noop"
    timeline: list[MCPToolExecution] = Field(default_factory=list)
    compensating_actions: int = 0
    timed_out: bool = False
    escalation_required: bool = True
    rollback_note: str | None = None
    total_duration_ms: int = 0
    detail: str = ""


def _is_compensatable(tool: str) -> bool:
    if tool in _NON_COMPENSATABLE_TOOLS:
        return False
    return not any(tool.startswith(p) for p in _NON_COMPENSATABLE_PREFIXES)


def rollback(
    runbook_timeline: list[MCPToolExecution],
    *,
    rollback_note: str | None = None,
    workload_id: str | None = None,
    registry: ConnectorRegistry | None = None,
    budget_ms: int | None = None,
) -> RollbackOutcome:
    """Reverse the successful steps of a runbook, then mark for escalation.

    Args:
        runbook_timeline: the executions produced by the runbook executor. Only
            steps with ``status == "success"`` are compensated, in reverse order.
        rollback_note: the recommendation's rollback note, attached to every
            compensating action and used for steps without a connector inverse.
        workload_id: target workload, threaded into compensating tool params.
        registry: connector registry used to execute compensating tools.
        budget_ms: rollback time budget; defaults to the policy timer. Pass a
            tiny value to exercise the timeout path quickly.

    Returns:
        A :class:`RollbackOutcome`. ``escalation_required`` is always ``True``:
        a verification failure means a human must take over even after a clean
        rollback (Requirement 8.3).
    """
    if registry is None:
        registry = ConnectorRegistry()
    if budget_ms is None:
        budget_ms = rollback_budget_ms()

    # Compensate successful, reversible steps in reverse execution order.
    applied = [
        ex
        for ex in runbook_timeline
        if ex.status == "success" and _is_compensatable(ex.tool)
    ]
    applied.reverse()

    timeline: list[MCPToolExecution] = []
    elapsed_ms = 0
    timed_out = False
    compensating_actions = 0

    for ex in applied:
        if timed_out:
            timeline.append(
                _skipped_compensation(
                    ex.tool, workload_id, rollback_note, "skipped: rollback aborted"
                )
            )
            continue

        inverse_tool = INVERSE_TOOL_MAP.get(ex.tool)
        if inverse_tool is None:
            # No connector-level inverse: record a documented no-op compensation.
            timeline.append(
                _skipped_compensation(
                    ex.tool,
                    workload_id,
                    rollback_note,
                    f"no automated inverse for '{ex.tool}'; manual compensation "
                    "per rollback_note",
                )
            )
            continue

        params: dict[str, Any] = {}
        if workload_id:
            params["workload_id"] = workload_id
        execution = registry.execute(inverse_tool, **params)
        # Annotate the compensation with provenance.
        execution = execution.model_copy(
            update={
                "output": {
                    **execution.output,
                    "rollback_of": ex.tool,
                    "rollback_note": rollback_note,
                }
            }
        )
        elapsed_ms += execution.duration_ms
        compensating_actions += 1

        if elapsed_ms > budget_ms:
            timed_out = True
            execution = execution.model_copy(
                update={
                    "status": "failed",
                    "output": {
                        **execution.output,
                        "status": "failed",
                        "error": "rollback_timeout",
                        "message": (
                            f"Rollback exceeded its {budget_ms}ms budget at "
                            f"'{inverse_tool}'."
                        ),
                    },
                }
            )
        timeline.append(execution)

    if not applied:
        status = "noop"
        detail = "No reversible actions to compensate."
    elif timed_out:
        status = "timed_out"
        detail = f"Rollback aborted after exceeding the {budget_ms}ms budget."
    elif all(ex.status in ("success", "skipped") for ex in timeline):
        status = "completed"
        detail = "All reversible actions compensated; escalating to a human."
    else:
        status = "partial"
        detail = "Some compensating actions failed; escalating to a human."

    outcome = RollbackOutcome(
        status=status,
        timeline=timeline,
        compensating_actions=compensating_actions,
        timed_out=timed_out,
        escalation_required=True,
        rollback_note=rollback_note,
        total_duration_ms=elapsed_ms,
        detail=detail,
    )
    logger.debug(
        "Rollback %s: %d compensating actions, timed_out=%s",
        status,
        compensating_actions,
        timed_out,
    )
    return outcome


def _skipped_compensation(
    forward_tool: str,
    workload_id: str | None,
    rollback_note: str | None,
    message: str,
) -> MCPToolExecution:
    return MCPToolExecution(
        tool=f"compensate:{forward_tool}",
        category="rollback",
        input={"workload_id": workload_id},
        output={
            "status": "skipped",
            "rollback_of": forward_tool,
            "rollback_note": rollback_note,
            "message": message,
        },
        duration_ms=0,
        status="skipped",
    )
