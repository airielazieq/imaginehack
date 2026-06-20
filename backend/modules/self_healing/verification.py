"""Post-fix verification for Module 3 (Guardrailed Self-Healing) — task 5.3.

After a runbook completes, the engine must confirm the fix actually worked
(Requirement 8.2): a health re-check that must pass *within 30 seconds*. This
module performs that check in a **simulated, deterministic, fast** way — there
are no real sleeps, so tests run instantly. Timing is simulated by accumulating
a small per-check cost and comparing it against the verification budget
(``verification_timeout_seconds`` from ``safety_rules.json``).

A verification can fail for two reasons:

* the post-fix health probe reports the workload is still unhealthy, or
* the simulated verification time exceeds the budget (a timeout).

Either way the result is ``"failed"`` and the caller (the composed auto-fix
path) must trigger a rollback and escalate.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from pydantic import BaseModel, Field

from backend.core.config import load_policy
from backend.modules.self_healing.runbook_executor import RunbookExecutionResult

logger = logging.getLogger("clover.self_healing.verification")

# Fallback budget if the policy file omits the timer (seconds).
_DEFAULT_VERIFICATION_TIMEOUT_SECONDS = 30
# Deterministic simulated cost per health check (milliseconds).
_SIMULATED_CHECK_COST_MS = 50

# A health probe takes the workload_id and returns True when healthy.
HealthProbe = Callable[[str | None], bool]


def verification_budget_ms(policy: dict[str, Any] | None = None) -> int:
    """Return the verification budget in milliseconds from policy timers."""
    if policy is None:
        policy = load_policy("safety_rules")
    timers = policy.get("timers", {}) if isinstance(policy, dict) else {}
    seconds = timers.get(
        "verification_timeout_seconds", _DEFAULT_VERIFICATION_TIMEOUT_SECONDS
    )
    return int(seconds * 1000)


class VerificationOutcome(BaseModel):
    """Result of a post-fix health verification."""

    result: str  # "passed" | "failed" | "skipped"
    healthy: bool
    timed_out: bool = False
    duration_ms: int
    checks: list[str] = Field(default_factory=list)
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.result == "passed"


def verify(
    workload_id: str | None,
    runbook_result: RunbookExecutionResult,
    *,
    health_probe: HealthProbe | None = None,
    simulate_healthy: bool | None = None,
    budget_ms: int | None = None,
    check_cost_ms: int = _SIMULATED_CHECK_COST_MS,
) -> VerificationOutcome:
    """Run a simulated post-fix health check.

    Args:
        workload_id: the workload that was remediated (passed to the probe).
        runbook_result: the timeline from the runbook executor. If the runbook
            itself did not succeed, verification is recorded as ``failed``
            without running probes (there is nothing healthy to confirm).
        health_probe: optional callable ``(workload_id) -> bool`` deciding
            health. When omitted, health defaults to ``True`` (the runbook
            succeeded) unless overridden by ``simulate_healthy``.
        simulate_healthy: explicit override for the health outcome — useful in
            tests to inject a verification failure deterministically.
        budget_ms: verification time budget; defaults to the policy timer.
            Pass a tiny value to exercise the timeout path quickly.
        check_cost_ms: simulated cost charged per health check.

    Returns:
        A :class:`VerificationOutcome`.
    """
    if budget_ms is None:
        budget_ms = verification_budget_ms()

    # Nothing to verify if the runbook did not complete successfully.
    if not runbook_result.succeeded:
        return VerificationOutcome(
            result="failed",
            healthy=False,
            timed_out=runbook_result.timed_out,
            duration_ms=0,
            checks=[],
            detail=(
                "Runbook did not complete successfully "
                f"(status={runbook_result.status}); skipping health probes "
                "and treating verification as failed."
            ),
        )

    # Simulated health checks. Deterministic, no real sleeps.
    checks = [
        "workload_reachable",
        "telemetry_within_healthy_bounds",
        "no_active_anomaly",
    ]
    duration_ms = len(checks) * check_cost_ms

    if duration_ms > budget_ms:
        logger.debug(
            "Verification timed out: %dms > %dms budget", duration_ms, budget_ms
        )
        return VerificationOutcome(
            result="failed",
            healthy=False,
            timed_out=True,
            duration_ms=duration_ms,
            checks=checks,
            detail=(
                f"Verification exceeded its {budget_ms}ms budget "
                f"({duration_ms}ms of checks)."
            ),
        )

    if simulate_healthy is not None:
        healthy = simulate_healthy
    elif health_probe is not None:
        healthy = bool(health_probe(workload_id))
    else:
        healthy = True

    outcome = VerificationOutcome(
        result="passed" if healthy else "failed",
        healthy=healthy,
        timed_out=False,
        duration_ms=duration_ms,
        checks=checks,
        detail=(
            "Workload returned to a healthy state after remediation."
            if healthy
            else "Workload remained unhealthy after remediation."
        ),
    )
    logger.debug("Verification result=%s for workload=%s", outcome.result, workload_id)
    return outcome
