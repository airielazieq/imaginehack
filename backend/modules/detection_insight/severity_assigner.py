"""Severity and confidence assignment for matched detection rules.

Given a :class:`~backend.modules.detection_insight.rule_classifier.RuleMatch`
and the workload context, this module produces:

  - ``severity``: one of ``low | medium | high | critical``, derived from the
    rule's ``severity_hint`` (keyed by production vs non-production) and then
    escalated for high-criticality workflows.
  - ``confidence_score``: a value in ``[0, 1]`` reflecting how specific the rule
    is (more conditions => more specific) and how strongly the numeric
    conditions are exceeded.

Severity is deterministic and rule-driven; it never depends on ML or LLM
output, matching the spec's "rules are authoritative" decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.modules.detection_insight.rule_classifier import RuleMatch

logger = logging.getLogger("clover.detection.severity_assigner")

# Severity ordering used for escalation arithmetic.
_SEVERITY_ORDER: list[str] = ["low", "medium", "high", "critical"]
_SEVERITY_INDEX: dict[str, int] = {s: i for i, s in enumerate(_SEVERITY_ORDER)}

_PRODUCTION = "production"
_NON_PRODUCTION_KEY = "non_production"
_DEFAULT_KEY = "default"

# How many severity levels to escalate based on workflow criticality.
_CRITICALITY_ESCALATION: dict[str, int] = {
    "critical": 1,
    "high": 1,
    "medium": 0,
    "low": 0,
}


@dataclass
class SeverityAssessment:
    """Result of severity + confidence assignment for a rule match."""

    severity: str
    confidence_score: float


def _clamp_severity(index: int) -> str:
    index = max(0, min(index, len(_SEVERITY_ORDER) - 1))
    return _SEVERITY_ORDER[index]


def _base_severity(rule_match: RuleMatch, environment: str | None) -> str:
    """Pick the severity hint for the environment, falling back to default."""
    hint = rule_match.severity_hint or {}

    if environment == _PRODUCTION and _PRODUCTION in hint:
        return hint[_PRODUCTION]
    if environment is not None and environment != _PRODUCTION and _NON_PRODUCTION_KEY in hint:
        return hint[_NON_PRODUCTION_KEY]
    if _DEFAULT_KEY in hint:
        return hint[_DEFAULT_KEY]
    # Last resort: any value present, else "medium".
    if hint:
        return next(iter(hint.values()))
    return "medium"


def _escalate(base_severity: str, workflow_criticality: str | None) -> str:
    """Escalate severity for high/critical workflow criticality.

    A ``high`` criticality only bumps a ``medium`` finding (so routine medium
    issues on important workflows surface as high), while ``critical``
    criticality always bumps one level. Capped at ``critical``.
    """
    base_index = _SEVERITY_INDEX.get(base_severity, _SEVERITY_INDEX["medium"])
    bump = _CRITICALITY_ESCALATION.get((workflow_criticality or "").lower(), 0)

    if workflow_criticality == "high" and base_severity != "medium":
        # "high" criticality only escalates a medium baseline.
        bump = 0

    return _clamp_severity(base_index + bump)


def _condition_strength(condition: dict[str, Any], evidence: dict[str, Any]) -> float:
    """Estimate how strongly a single condition is met (0.5 .. 1.0).

    Exact matches (eq/neq/in) are treated as full strength. Numeric thresholds
    score by how far the actual value passes the threshold, so a value far past
    the bound yields higher confidence than one that barely crosses it.
    """
    operator = condition.get("operator")
    field_name = condition.get("field")
    expected = condition.get("value")

    if operator in {"eq", "neq", "in"}:
        return 1.0

    actual = evidence.get(field_name)
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return 0.75
    if not isinstance(expected, (int, float)) or isinstance(expected, bool):
        return 0.75

    threshold = float(expected)
    value = float(actual)

    # Fractional margin past the threshold, normalised against the threshold
    # magnitude. A 100% overshoot saturates to full strength.
    denom = abs(threshold) if threshold != 0 else 1.0
    if operator in {"gt", "gte"}:
        margin = (value - threshold) / denom
    else:  # lt, lte -> stronger as the value drops below the threshold
        margin = (threshold - value) / denom

    margin = max(0.0, margin)
    return min(1.0, 0.5 + 0.5 * min(margin, 1.0))


def _compute_confidence(rule_match: RuleMatch) -> float:
    """Combine rule specificity and condition strength into [0, 1]."""
    conditions = rule_match.conditions or []
    num_conditions = len(conditions)

    # Specificity: more conditions => a more specific (and confident) match.
    specificity = min(1.0, 0.55 + 0.15 * num_conditions)

    if num_conditions:
        strengths = [_condition_strength(c, rule_match.evidence) for c in conditions]
        avg_strength = sum(strengths) / len(strengths)
    else:
        avg_strength = 1.0

    confidence = specificity * (0.7 + 0.3 * avg_strength)
    return round(max(0.0, min(1.0, confidence)), 2)


def assign_severity(
    rule_match: RuleMatch,
    workload: Any | None = None,
    environment: str | None = None,
    workflow_criticality: str | None = None,
) -> SeverityAssessment:
    """Assign a severity and confidence score to a matched rule.

    Args:
        rule_match: The fired rule (carries the ``severity_hint``).
        workload: Optional ``Workload`` (or mapping) used to read
            ``environment`` and ``workflow_criticality`` when not passed
            explicitly.
        environment: Overrides the workload environment when provided.
        workflow_criticality: Overrides the workload criticality when provided.

    Returns:
        A :class:`SeverityAssessment` with the final severity and a confidence
        score in ``[0, 1]``.
    """
    env = environment
    crit = workflow_criticality

    if (env is None or crit is None) and workload is not None:
        if hasattr(workload, "model_dump"):
            wl = workload.model_dump()
        elif isinstance(workload, dict):
            wl = workload
        else:
            wl = getattr(workload, "__dict__", {})
        if env is None:
            env = wl.get("environment")
        if crit is None:
            crit = wl.get("workflow_criticality")

    base = _base_severity(rule_match, env)
    severity = _escalate(base, crit)
    confidence = _compute_confidence(rule_match)

    logger.debug(
        "Rule %s -> severity=%s (base=%s, env=%s, crit=%s), confidence=%.2f",
        rule_match.rule_id,
        severity,
        base,
        env,
        crit,
        confidence,
    )
    return SeverityAssessment(severity=severity, confidence_score=confidence)
