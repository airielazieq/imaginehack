"""Risk level + execution mode assignment for Module 2 (Next Best Action).

This component is the deterministic safety brain of the recommendation engine.
Given the matched recommendation rule and the workload context, it answers two
questions (per SDD 05 sections 5 and 6):

  1. **Risk level** ``low | medium | high | critical`` derived from the
     workload environment, the action's reversibility, security / sensitive
     data exposure, and the workflow criticality.

  2. **Required execution mode** ``auto_fix | user_approval_required |
     human_escalation_required`` selected from the risk level *combined with*
     the rule's own ``execution_mode_policy`` baseline.

Design rules honoured here:

  - The rule's ``execution_mode_policy`` (``production`` vs ``non_production``)
    is the **baseline** mode. The risk-derived mode can only *escalate* above
    that baseline, never relax below it (we take the more restrictive of the
    two).
  - ``critical`` risk **always** routes to ``human_escalation_required``,
    regardless of the rule policy or any other condition.

Mapping (SDD 05 section 5 - risk level):

    | Context                                                   | Risk     |
    |-----------------------------------------------------------|----------|
    | production + security / sensitive data exposure           | critical |
    | production + irreversible / config change                 | high     |
    | production (other)                                        | high     |
    | staging + reversible + criticality <= medium              | medium   |
    | staging / high criticality non-prod                       | medium   |
    | development|testing + reversible + criticality <= medium  | low      |

Mapping (SDD 05 section 6 - execution mode from risk):

    | Risk     | Mode                       |
    |----------|----------------------------|
    | low      | auto_fix                   |
    | medium   | user_approval_required     |
    | high     | user_approval_required     |
    | critical | human_escalation_required  |

Everything here is deterministic and never depends on ML or LLM output.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("clover.nba.risk_assessor")

# Valid output literals (mirrors the Recommendation schema).
RISK_LEVELS = ("low", "medium", "high", "critical")
EXECUTION_MODES = (
    "auto_fix",
    "user_approval_required",
    "human_escalation_required",
)

# Restrictiveness ordering for execution modes; higher index == more restrictive.
_MODE_ORDER = {mode: i for i, mode in enumerate(EXECUTION_MODES)}

# Risk level -> the execution mode that risk alone implies.
_RISK_TO_MODE: dict[str, str] = {
    "low": "auto_fix",
    "medium": "user_approval_required",
    "high": "user_approval_required",
    "critical": "human_escalation_required",
}

_PRODUCTION = "production"
# Environments treated as "true" non-production (eligible for auto_fix at low risk).
_DEV_TEST = {"development", "testing"}
_STAGING = "staging"

_LOWER_CRITICALITY = {"low", "medium"}


@dataclass
class RiskAssessment:
    """Outcome of risk + execution-mode assessment for a recommendation."""

    risk_level: str
    required_execution_mode: str
    approval_required: bool
    reversible: bool
    reasons: list[str] = field(default_factory=list)


def _policy_baseline_mode(execution_mode_policy: dict[str, str] | None, environment: str | None) -> str:
    """Return the rule's baseline execution mode for the environment class.

    ``execution_mode_policy`` has ``production`` and ``non_production`` keys.
    Production workloads use the ``production`` entry; everything else (staging,
    testing, development) uses ``non_production``. Falls back to
    ``user_approval_required`` when the policy is missing/incomplete.
    """
    policy = execution_mode_policy or {}
    if environment == _PRODUCTION:
        return policy.get(_PRODUCTION, "user_approval_required")
    return policy.get("non_production", "user_approval_required")


def _more_restrictive(mode_a: str, mode_b: str) -> str:
    """Return whichever execution mode is the more restrictive of the two."""
    return mode_a if _MODE_ORDER.get(mode_a, 0) >= _MODE_ORDER.get(mode_b, 0) else mode_b


def assess_risk(
    *,
    environment: str | None,
    action_category: str,
    recommendation_type: str,
    workflow_criticality: str | None,
    reversible: bool,
    is_security: bool = False,
    issue_severity: str | None = None,
) -> tuple[str, list[str]]:
    """Compute the risk level for a recommendation.

    Args:
        environment: Workload environment (``production``, ``staging``,
            ``testing``, ``development``).
        action_category: The recommendation's action category (e.g. ``security``).
        recommendation_type: The recommendation type (e.g. ``restrict_access``).
        workflow_criticality: ``critical | high | medium | low``.
        reversible: Whether the action can be rolled back (a ``rollback_note``
            exists / the action is not destructive).
        is_security: Whether this is a security / sensitive-data action.
        issue_severity: Originating issue severity, used as a secondary
            escalator for production findings.

    Returns:
        ``(risk_level, reasons)`` where ``reasons`` documents the decision for
        audit traceability.
    """
    env = (environment or "").lower()
    crit = (workflow_criticality or "").lower()
    security = is_security or action_category == "security"
    reasons: list[str] = []

    is_production = env == _PRODUCTION

    if is_production and (security or issue_severity == "critical"):
        reasons.append(
            "production workload with security / sensitive-data exposure -> critical"
        )
        return "critical", reasons

    if is_production:
        if not reversible:
            reasons.append("production workload with an irreversible action -> high")
        else:
            reasons.append("production workload config/availability change -> high")
        return "high", reasons

    if env == _STAGING:
        if crit in {"high", "critical"}:
            reasons.append("staging workload with high criticality -> high")
            return "high", reasons
        reasons.append("staging workload, reversible, criticality<=medium -> medium")
        return "medium", reasons

    # development / testing (true non-production) or unknown.
    if crit in {"high", "critical"}:
        reasons.append("non-production workload with high criticality -> medium")
        return "medium", reasons
    if reversible and crit in _LOWER_CRITICALITY:
        reasons.append(
            "non-production, reversible, criticality<=medium -> low"
        )
        return "low", reasons
    if not reversible:
        reasons.append("non-production but irreversible action -> medium")
        return "medium", reasons
    # Unknown criticality on non-prod: be conservative.
    reasons.append("non-production with unknown criticality -> medium")
    return "medium", reasons


def select_execution_mode(
    risk_level: str,
    execution_mode_policy: dict[str, str] | None,
    environment: str | None,
) -> tuple[str, list[str]]:
    """Select the required execution mode from risk + the rule policy baseline.

    The rule's ``execution_mode_policy`` is the baseline for the environment
    class; the risk-derived mode can only escalate above it. ``critical`` risk
    always routes to ``human_escalation_required``.
    """
    reasons: list[str] = []

    if risk_level == "critical":
        reasons.append("critical risk always escalates -> human_escalation_required")
        return "human_escalation_required", reasons

    baseline = _policy_baseline_mode(execution_mode_policy, environment)
    risk_mode = _RISK_TO_MODE.get(risk_level, "user_approval_required")
    final = _more_restrictive(baseline, risk_mode)

    reasons.append(
        f"baseline={baseline} (policy/{'production' if environment == _PRODUCTION else 'non_production'}), "
        f"risk_mode={risk_mode} (risk={risk_level}) -> {final}"
    )
    return final, reasons


def assess(
    *,
    environment: str | None,
    action_category: str,
    recommendation_type: str,
    workflow_criticality: str | None,
    reversible: bool,
    execution_mode_policy: dict[str, str] | None,
    is_security: bool = False,
    issue_severity: str | None = None,
) -> RiskAssessment:
    """Full risk + execution-mode assessment for a matched recommendation rule.

    Combines :func:`assess_risk` and :func:`select_execution_mode` and returns
    a single :class:`RiskAssessment`.
    """
    risk_level, risk_reasons = assess_risk(
        environment=environment,
        action_category=action_category,
        recommendation_type=recommendation_type,
        workflow_criticality=workflow_criticality,
        reversible=reversible,
        is_security=is_security,
        issue_severity=issue_severity,
    )
    mode, mode_reasons = select_execution_mode(
        risk_level, execution_mode_policy, environment
    )

    logger.debug(
        "Risk=%s, mode=%s (env=%s, type=%s, crit=%s, reversible=%s)",
        risk_level,
        mode,
        environment,
        recommendation_type,
        workflow_criticality,
        reversible,
    )

    return RiskAssessment(
        risk_level=risk_level,
        required_execution_mode=mode,
        approval_required=mode != "auto_fix",
        reversible=reversible,
        reasons=[*risk_reasons, *mode_reasons],
    )
