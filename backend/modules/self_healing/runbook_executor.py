"""Runbook executor for Module 3 (Guardrailed Self-Healing) — task 5.3.

A *runbook* is an ordered list of MCP tool steps derived from a
:class:`~backend.schemas.recommendation.Recommendation`'s ``mcp_tools``. This
module executes those steps **sequentially** through the appropriate simulated
connector (resolved by the
:class:`~backend.connectors.ConnectorRegistry`: cloud tools -> CloudConnector,
``create_ticket`` -> TicketingConnector, ``notify_*`` -> NotificationConnector,
``write_audit_log`` -> AuditConnector) and collects an
:class:`~backend.schemas.remediation.MCPToolExecution` for each — the execution
timeline that the report generator (task 5.5) surfaces to operators.

Key behaviours
--------------
* **Short-circuit on failure** — once a step fails (or the runbook budget is
  exhausted), remaining steps are not executed; they are recorded as
  ``skipped`` so the timeline stays complete.
* **Budget / timeout simulation** — connectors return a deterministic simulated
  ``duration_ms`` (no real sleeps). The executor accumulates this simulated
  elapsed time and aborts if it exceeds the runbook budget
  (``runbook_timeout_seconds`` from ``safety_rules.json``, overridable for
  fast tests).
* **Deterministic** — identical inputs yield an identical timeline, so reports
  and tests are reproducible.

This module deliberately does *not* assemble a full ``RemediationResult`` or
expose an API — that is task 5.5. It returns enough structured data for 5.5 to
build the final record. The composed auto-fix entry point
(:func:`run_auto_fix`) lives in :mod:`backend.modules.self_healing.healer`.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from pydantic import BaseModel, Field

from backend.connectors import ConnectorRegistry
from backend.core.config import load_policy
from backend.schemas.remediation import MCPToolExecution

logger = logging.getLogger("clover.self_healing.runbook_executor")

# Fallback budget if the policy file omits the timer (seconds).
_DEFAULT_RUNBOOK_TIMEOUT_SECONDS = 120


def runbook_budget_ms(policy: dict[str, Any] | None = None) -> int:
    """Return the runbook execution budget in milliseconds from policy timers."""
    if policy is None:
        policy = load_policy("safety_rules")
    timers = policy.get("timers", {}) if isinstance(policy, dict) else {}
    seconds = timers.get("runbook_timeout_seconds", _DEFAULT_RUNBOOK_TIMEOUT_SECONDS)
    return int(seconds * 1000)


def runbook_tools_by_type(policy: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """Build the ``recommendation_type -> ordered MCP tools`` map from policy.

    Derived from ``recommendation_rules.json``: each rule declares a
    ``recommendation_type`` and the ordered ``mcp_tools`` that implement it. This
    is the canonical mapping the runbook executor uses when a recommendation does
    not carry its own ``mcp_tools`` list.

    When several rules share a ``recommendation_type`` (e.g. two security rules
    both map to ``restrict_access``) the **first** rule declared wins, keeping
    the mapping deterministic. The returned dict is a fresh copy so callers may
    mutate it freely.
    """
    if policy is None:
        policy = load_policy("recommendation_rules")
    rules = policy.get("rules", []) if isinstance(policy, dict) else []
    mapping: dict[str, list[str]] = {}
    for rule in rules:
        rec_type = rule.get("recommendation_type")
        tools = rule.get("mcp_tools") or []
        if rec_type and rec_type not in mapping:
            mapping[rec_type] = list(tools)
    return mapping


def runbook_steps_for_recommendation_type(
    recommendation_type: str,
    policy: dict[str, Any] | None = None,
) -> list[str]:
    """Return the ordered MCP tool names for a ``recommendation_type``.

    Looks the type up in :func:`runbook_tools_by_type`. Returns an empty list
    for an unknown type (the caller then produces an empty/no-op runbook rather
    than raising).
    """
    return list(runbook_tools_by_type(policy).get(recommendation_type, []))


class RunbookStep(BaseModel):
    """A single tool invocation within a runbook."""

    tool: str
    params: dict[str, Any] = Field(default_factory=dict)


class RunbookExecutionResult(BaseModel):
    """Outcome of executing a runbook (the execution timeline + summary)."""

    status: str  # "success" | "failed" | "timed_out"
    timeline: list[MCPToolExecution]
    steps_total: int
    steps_executed: int
    steps_succeeded: int
    failed_tool: str | None = None
    timed_out: bool = False
    total_duration_ms: int

    @property
    def succeeded(self) -> bool:
        return self.status == "success"


def build_runbook(
    recommendation: Any,
    *,
    extra_params: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> list[RunbookStep]:
    """Derive an ordered runbook from a Recommendation.

    The tool sequence is taken from the recommendation's own ``mcp_tools`` when
    present. If that list is empty/absent, the runbook is derived from the
    recommendation's ``recommendation_type`` via
    :func:`runbook_steps_for_recommendation_type` (the canonical
    ``recommendation_rules.json`` mapping). This lets the executor build a
    runbook from nothing more than a recommendation type.

    Each tool becomes a :class:`RunbookStep` carrying the target ``workload_id``
    (when available) so the simulated connectors can record which workload was
    acted upon. ``extra_params`` are merged into every step for callers that
    need to thread additional context (e.g. ticket title, owner team).
    """
    rec = _as_dict(recommendation)
    tools: Iterable[str] = rec.get("mcp_tools") or []
    if not tools and rec.get("recommendation_type"):
        tools = runbook_steps_for_recommendation_type(
            rec["recommendation_type"], policy
        )

    base_params: dict[str, Any] = {}
    if rec.get("workload_id"):
        base_params["workload_id"] = rec["workload_id"]
    if extra_params:
        base_params.update(extra_params)

    return [RunbookStep(tool=tool, params=dict(base_params)) for tool in tools]


class RunbookExecutor:
    """Executes runbook steps sequentially via a :class:`ConnectorRegistry`."""

    def __init__(
        self,
        registry: ConnectorRegistry | None = None,
        *,
        budget_ms: int | None = None,
    ) -> None:
        self.registry = registry if registry is not None else ConnectorRegistry()
        self.budget_ms = budget_ms if budget_ms is not None else runbook_budget_ms()

    def execute(
        self,
        steps: list[RunbookStep],
        *,
        failing_tools: set[str] | None = None,
    ) -> RunbookExecutionResult:
        """Run ``steps`` in order, short-circuiting on the first failure.

        Args:
            steps: ordered runbook steps to execute.
            failing_tools: optional set of tool names to force into a ``failed``
                execution (used to simulate connector/runtime failures in tests
                without mutating the connectors themselves).

        Returns:
            A :class:`RunbookExecutionResult` with the full timeline. Steps that
            run after a failure or after the budget is exhausted are recorded as
            ``skipped`` so the timeline length always equals ``len(steps)``.
        """
        failing_tools = failing_tools or set()
        timeline: list[MCPToolExecution] = []
        elapsed_ms = 0
        steps_executed = 0
        steps_succeeded = 0
        failed_tool: str | None = None
        timed_out = False
        aborted = False

        for step in steps:
            if aborted:
                timeline.append(self._skipped(step, "skipped: runbook aborted"))
                continue

            execution = self.registry.execute(step.tool, **step.params)

            # Inject a simulated failure for the requested tools.
            if step.tool in failing_tools:
                execution = execution.model_copy(
                    update={
                        "status": "failed",
                        "output": {
                            **execution.output,
                            "status": "failed",
                            "error": "simulated_step_failure",
                        },
                    }
                )

            elapsed_ms += execution.duration_ms
            steps_executed += 1

            # Budget exhausted by (and including) this step -> timeout abort.
            if elapsed_ms > self.budget_ms:
                timed_out = True
                aborted = True
                timeout_exec = execution.model_copy(
                    update={
                        "status": "failed",
                        "output": {
                            **execution.output,
                            "status": "failed",
                            "error": "runbook_timeout",
                            "message": (
                                f"Runbook exceeded its {self.budget_ms}ms budget "
                                f"at tool '{step.tool}'."
                            ),
                        },
                    }
                )
                timeline.append(timeout_exec)
                failed_tool = step.tool
                continue

            timeline.append(execution)

            if execution.status == "success":
                steps_succeeded += 1
            else:
                failed_tool = step.tool
                aborted = True

        if timed_out:
            status = "timed_out"
        elif failed_tool is not None:
            status = "failed"
        else:
            status = "success"

        result = RunbookExecutionResult(
            status=status,
            timeline=timeline,
            steps_total=len(steps),
            steps_executed=steps_executed,
            steps_succeeded=steps_succeeded,
            failed_tool=failed_tool,
            timed_out=timed_out,
            total_duration_ms=elapsed_ms,
        )
        logger.debug(
            "Runbook executed: status=%s steps=%d/%d failed_tool=%s timed_out=%s",
            status,
            steps_succeeded,
            len(steps),
            failed_tool,
            timed_out,
        )
        return result

    @staticmethod
    def _skipped(step: RunbookStep, message: str) -> MCPToolExecution:
        return MCPToolExecution(
            tool=step.tool,
            category="runbook",
            input=dict(step.params),
            output={"status": "skipped", "message": message},
            duration_ms=0,
            status="skipped",
        )


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
    raise TypeError(f"Cannot build a runbook from {type(obj)!r}")
