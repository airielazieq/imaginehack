"""Rule-based issue classification for Module 1 (Detection & Insight).

This component answers *what* is wrong with a workload. The Isolation Forest
(task 3.2) flags *that* something is abnormal; the rules here classify the
finding into one of the 7 defined ``issue_type`` values and a category.

Rules live in ``backend/rules/detection_rules.json`` (policy-as-data) and run
independently of the ML model, so "obvious" issues are caught even when the
model is cold.

Each rule has:
  - ``id``            e.g. ``DET-SEC-001``
  - ``issue_type``    one of the 7 defined types
  - ``category``      the Issue category
  - ``logic``         ``"all"`` (every condition) or ``"any"`` (at least one)
  - ``conditions``    list of ``{field, operator, value | value_ref}``
  - ``severity_hint`` per-environment + ``default`` severity (used by the
                      severity_assigner, carried through on the match)

Supported operators: ``eq, neq, lt, lte, gt, gte, in``. A condition may supply
either an inline ``value`` or a ``value_ref`` naming a top-level list in the
policy (e.g. ``batch_workflows``) which is resolved at evaluation time.

Fields are resolved from a merged context built from the ``TelemetrySnapshot``
and the optional ``Workload`` (so rules can reference ``environment`` and
``construction_workflow`` which live on the workload).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.core.config import load_policy

logger = logging.getLogger("clover.detection.rule_classifier")

# Operators the rule engine understands. Each maps to a comparison callable.
_NUMERIC_OPERATORS = {"lt", "lte", "gt", "gte"}
_SUPPORTED_OPERATORS = {"eq", "neq", "in"} | _NUMERIC_OPERATORS


@dataclass
class RuleMatch:
    """A single detection rule that fired against a telemetry/workload context.

    Attributes:
        rule_id: The rule identifier (e.g. ``DET-SEC-001``).
        issue_type: The classified issue type.
        issue_category: The issue category.
        conditions_matched: Human-readable description of each satisfied
            condition, suitable for audit traceability.
        severity_hint: The rule's per-environment severity hint, forwarded for
            the severity_assigner.
        conditions: The raw condition dicts (used to gauge specificity).
        evidence: Field -> actual value map for every field the rule evaluated.
    """

    rule_id: str
    issue_type: str
    issue_category: str
    conditions_matched: list[str]
    severity_hint: dict[str, str] = field(default_factory=dict)
    conditions: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def _to_plain(obj: Any) -> Any:
    """Return a plain dict for a Pydantic model or pass through a mapping."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    # Pydantic v2 model.
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    # Pydantic v1 / generic object with __dict__.
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    raise TypeError(f"Cannot build a field context from {type(obj)!r}")


def build_context(telemetry: Any, workload: Any | None = None) -> dict[str, Any]:
    """Merge telemetry and workload fields into a single lookup context.

    Telemetry provides the runtime metrics; the workload (when supplied)
    contributes ``environment``, ``construction_workflow``, ``workflow_criticality``
    and other static attributes that detection rules reference. Telemetry values
    take precedence on key collisions (e.g. ``workload_id``).
    """
    context: dict[str, Any] = {}
    context.update(_to_plain(workload))
    context.update(_to_plain(telemetry))
    return context


def _resolve_expected(condition: dict[str, Any], policy: dict[str, Any]) -> Any:
    """Resolve a condition's expected value (inline ``value`` or ``value_ref``)."""
    if "value_ref" in condition:
        ref = condition["value_ref"]
        if ref not in policy:
            raise KeyError(
                f"value_ref '{ref}' not found among detection policy top-level keys"
            )
        return policy[ref]
    return condition.get("value")


def _compare(operator: str, actual: Any, expected: Any) -> bool:
    """Apply a single operator. Returns False on type errors rather than raising."""
    if operator == "eq":
        return actual == expected
    if operator == "neq":
        return actual != expected
    if operator == "in":
        try:
            return actual in expected
        except TypeError:
            return False
    if operator in _NUMERIC_OPERATORS:
        # Guard against booleans (bool is an int subclass) and non-numerics.
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        try:
            if operator == "lt":
                return actual < expected
            if operator == "lte":
                return actual <= expected
            if operator == "gt":
                return actual > expected
            if operator == "gte":
                return actual >= expected
        except TypeError:
            return False
    raise ValueError(f"Unsupported operator: {operator!r}")


def _describe(field_name: str, operator: str, expected: Any, actual: Any) -> str:
    """Build a human-readable description of a satisfied condition."""
    return f"{field_name} {operator} {expected!r} (actual={actual!r})"


def _evaluate_condition(
    condition: dict[str, Any],
    context: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[bool, str | None, tuple[str, Any] | None]:
    """Evaluate one condition.

    Returns ``(matched, description, (field, actual))``. ``description`` and the
    evidence tuple are populated only when the condition is satisfied.
    """
    field_name = condition["field"]
    operator = condition["operator"]
    if operator not in _SUPPORTED_OPERATORS:
        raise ValueError(f"Unsupported operator: {operator!r}")

    if field_name not in context:
        # Missing field (e.g. workload context not supplied) -> cannot match.
        return False, None, None

    actual = context[field_name]
    expected = _resolve_expected(condition, policy)
    matched = _compare(operator, actual, expected)
    if not matched:
        return False, None, None
    return True, _describe(field_name, operator, expected, actual), (field_name, actual)


def _rule_matches(
    rule: dict[str, Any],
    context: dict[str, Any],
    policy: dict[str, Any],
) -> RuleMatch | None:
    """Evaluate a single rule against the context, returning a match or None."""
    logic = rule.get("logic", "all")
    conditions = rule.get("conditions", [])

    descriptions: list[str] = []
    evidence: dict[str, Any] = {}
    satisfied = 0

    for condition in conditions:
        matched, description, ev = _evaluate_condition(condition, context, policy)
        if matched:
            satisfied += 1
            if description is not None:
                descriptions.append(description)
            if ev is not None:
                evidence[ev[0]] = ev[1]

    if logic == "all":
        fired = satisfied == len(conditions) and len(conditions) > 0
    elif logic == "any":
        fired = satisfied > 0
    else:
        raise ValueError(f"Unsupported rule logic: {logic!r}")

    if not fired:
        return None

    return RuleMatch(
        rule_id=rule["id"],
        issue_type=rule["issue_type"],
        issue_category=rule["category"],
        conditions_matched=descriptions,
        severity_hint=dict(rule.get("severity_hint", {})),
        conditions=list(conditions),
        evidence=evidence,
    )


def evaluate_rules(
    telemetry: Any,
    workload: Any | None = None,
    policy: dict[str, Any] | None = None,
) -> list[RuleMatch]:
    """Evaluate all detection rules against a telemetry snapshot.

    Args:
        telemetry: A ``TelemetrySnapshot`` (or a mapping of its fields).
        workload: The associated ``Workload`` (or mapping). Supplies the
            ``environment`` / ``construction_workflow`` fields some rules need.
        policy: Optional pre-loaded detection policy; defaults to the cached
            ``detection_rules.json`` from :func:`load_policy`.

    Returns:
        Every rule that fired, in policy declaration order. Empty when the
        workload is healthy.
    """
    if policy is None:
        policy = load_policy("detection_rules")

    context = build_context(telemetry, workload)
    matches: list[RuleMatch] = []
    for rule in policy.get("rules", []):
        match = _rule_matches(rule, context, policy)
        if match is not None:
            logger.debug(
                "Rule %s fired for workload %s (%s)",
                match.rule_id,
                context.get("workload_id"),
                match.issue_type,
            )
            matches.append(match)
    return matches


def classify(
    telemetry: Any,
    workload: Any | None = None,
    policy: dict[str, Any] | None = None,
) -> RuleMatch | None:
    """Return the single most relevant rule match, or ``None`` if healthy.

    When multiple rules fire, the first by policy declaration order is returned.
    Issue consolidation across a time window is handled by the detector (3.5);
    this helper simply offers a convenient "primary classification" accessor.
    """
    matches = evaluate_rules(telemetry, workload, policy)
    return matches[0] if matches else None
