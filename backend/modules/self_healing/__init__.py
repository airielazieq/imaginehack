"""Module 3: Guardrailed Self-Healing.

Subcomponents (built across tasks 5.1-5.5):
  - safety_router: deterministic safety-rule evaluation -> execution path
  - runbook_executor: sequential MCP-tool runbook execution (timeline)
  - verification: simulated post-fix health check (30s budget)
  - rollback: compensating MCP actions on verification failure (60s budget)
  - healer: composed auto-fix path (execute -> verify -> rollback -> escalate)

Later tasks add the approval queue (5.4) and report generator (5.5). The
runbook/verification/rollback primitives are side-effect free over simulated
connectors so 5.4/5.5 can compose them freely.
"""

from backend.modules.self_healing.healer import (  # noqa: F401
    SelfHealingExecution,
    execute_runbook,
    run_auto_fix,
)
from backend.modules.self_healing.rollback import (  # noqa: F401
    INVERSE_TOOL_MAP,
    RollbackOutcome,
    rollback,
    rollback_budget_ms,
)
from backend.modules.self_healing.runbook_executor import (  # noqa: F401
    RunbookExecutionResult,
    RunbookExecutor,
    RunbookStep,
    build_runbook,
    runbook_budget_ms,
    runbook_steps_for_recommendation_type,
    runbook_tools_by_type,
)
from backend.modules.self_healing.safety_router import (  # noqa: F401
    RemediationContext,
    SafetyRoutingDecision,
    build_remediation_context,
    route,
)
from backend.modules.self_healing.verification import (  # noqa: F401
    VerificationOutcome,
    verification_budget_ms,
    verify,
)

__all__ = [
    "RemediationContext",
    "SafetyRoutingDecision",
    "build_remediation_context",
    "route",
    "RunbookStep",
    "RunbookExecutor",
    "RunbookExecutionResult",
    "build_runbook",
    "runbook_budget_ms",
    "runbook_steps_for_recommendation_type",
    "runbook_tools_by_type",
    "VerificationOutcome",
    "verify",
    "verification_budget_ms",
    "RollbackOutcome",
    "rollback",
    "rollback_budget_ms",
    "INVERSE_TOOL_MAP",
    "SelfHealingExecution",
    "run_auto_fix",
    "execute_runbook",
]
