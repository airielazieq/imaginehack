"""Deterministic safety router for Module 3 (Guardrailed Self-Healing).

This is the authoritative gate that decides *how* a remediation is allowed to
run: ``auto_fix``, ``user_approval_required`` or ``human_escalation_required``.
The LLM never participates in this decision — routing is a pure function of the
safety policy (``backend/rules/safety_rules.json``) and a structured
:class:`RemediationContext`.

Routing precedence (Requirements 7.1-7.4)
-----------------------------------------
The path is chosen by the precedence declared in the policy's
``evaluation_order`` (blocklist -> escalation -> approval -> auto_fix), with a
critical-risk override on top:

1. ``risk_level == "critical"``                  -> human_escalation_required
2. any **blocklist** action matches              -> human_escalation_required
3. any **escalation** condition holds            -> human_escalation_required
4. any **approval** condition holds              -> user_approval_required
5. **all** auto-fix conditions hold (7 of 7)     -> auto_fix
6. default (nothing else matched)                -> user_approval_required

Evaluating approval *before* auto-fix is deliberate and strictly safer: auto-fix
is only reached when no escalation **and** no approval condition holds, so the
seven auto-fix conditions act as a necessary gate (Requirement 7.1). This avoids
the trap where an action that incidentally satisfies all seven conditions but
also (say) modifies config or runs in staging would otherwise auto-execute.

Rule 1 is also expressed inside the policy (``risk_level_critical`` escalation
condition); it is enforced explicitly here as well so the guarantee holds even
if the policy file is edited.

Determinism
-----------
``route`` has no randomness, no clock reads and no I/O beyond the cached policy
load. Conditions are evaluated in declaration order. Identical inputs therefore
always yield an identical :class:`SafetyRoutingDecision`.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.core.config import load_policy
from backend.schemas.remediation import SafetyDecision

logger = logging.getLogger("clover.self_healing.safety_router")

ExecutionPath = Literal[
    "auto_fix", "user_approval_required", "human_escalation_required"
]

# Operators understood by the safety policy. ``exists`` is unique to this policy
# (used for ``rollback_note``); the rest mirror the detection rule engine.
_NUMERIC_OPERATORS = {"lt", "lte", "gt", "gte"}
_SUPPORTED_OPERATORS = {"eq", "neq", "in", "exists"} | _NUMERIC_OPERATORS


class RemediationContext(BaseModel):
    """The safety-relevant facts about a single remediation.

    Built from a :class:`~backend.schemas.recommendation.Recommendation`, its
    target ``Workload`` and the properties of the concrete action to be taken.
    Every field carries a conservative default so callers only need to set the
    fields that are actually known; unknown booleans default to the *safe*
    interpretation (``False`` for "does this dangerous thing happen?").
    """

    # --- shared / identity ---------------------------------------------------
    environment: str = "production"
    workflow_criticality: str = "high"
    risk_level: str = "high"
    ai_confidence: float = 1.0

    # The action identifier(s) checked against the hard blocklist. ``action`` is
    # the primary key; ``action_keywords`` lets callers pass extra identifiers
    # (e.g. category / recommendation_type) without losing the primary action.
    action: str | None = None
    action_keywords: list[str] = Field(default_factory=list)

    # --- auto-fix gating facts ----------------------------------------------
    action_reversible: bool = False
    sensitive_data_affected: bool = False
    database_affected: bool = False
    network_or_security_policy_modified: bool = False
    rollback_note: str | None = None

    # --- approval facts ------------------------------------------------------
    affects_availability: bool = False
    modifies_config: bool = False
    changes_access_policy: bool = False
    requires_downtime: bool = False
    reversible_but_sensitive: bool = False

    # --- escalation facts ----------------------------------------------------
    critical_production_vulnerability: bool = False
    production_database_affected: bool = False
    unknown_dependency: bool = False
    may_cause_major_downtime: bool = False
    deletes_data: bool = False
    critical_network_or_security_policy: bool = False

    model_config = {"extra": "allow"}

    def field_value(self, name: str) -> Any:
        """Resolve a policy ``field`` name against this context.

        Supports the declared attributes plus any extra fields supplied via the
        permissive model config. Returns ``None`` when the field is absent so
        ``exists`` checks behave correctly.
        """
        if name in self.__dict__:
            return self.__dict__[name]
        extra = getattr(self, "__pydantic_extra__", None) or {}
        return extra.get(name)


class SafetyRoutingDecision(BaseModel):
    """The router's verdict plus a full audit trail of how it was reached."""

    execution_path: ExecutionPath
    approval_required: bool
    rollback_available: bool
    why_safe: str
    reasons: list[str]
    matched_conditions: list[str]
    blocklisted: bool
    blocklisted_action: str | None
    # group -> list of per-condition audit records (id, field, operator,
    # expected, actual, matched). Captures every condition that was evaluated.
    evaluated_conditions: dict[str, list[dict[str, Any]]]

    def to_safety_decision(self) -> SafetyDecision:
        """Project onto the persisted :class:`SafetyDecision` schema."""
        return SafetyDecision(
            why_safe=self.why_safe,
            approval_required=self.approval_required,
            rollback_available=self.rollback_available,
        )


def _compare(operator: str, actual: Any, expected: Any) -> bool:
    """Apply a single policy operator. Returns ``False`` on type mismatch."""
    if operator == "exists":
        present = actual is not None and actual != ""
        return present == bool(expected)
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
        # bool is an int subclass; never treat booleans as numbers here.
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
    raise ValueError(f"Unsupported operator: {operator!r}")


def _evaluate_condition(
    condition: dict[str, Any], context: RemediationContext
) -> dict[str, Any]:
    """Evaluate one condition and return an audit record."""
    field_name = condition["field"]
    operator = condition["operator"]
    if operator not in _SUPPORTED_OPERATORS:
        raise ValueError(f"Unsupported operator: {operator!r}")

    expected = condition.get("value")
    actual = context.field_value(field_name)
    matched = _compare(operator, actual, expected)
    return {
        "id": condition.get("id", field_name),
        "field": field_name,
        "operator": operator,
        "expected": expected,
        "actual": actual,
        "matched": matched,
    }


def _evaluate_group(
    group: dict[str, Any], context: RemediationContext
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    """Evaluate a condition group (``logic`` = ``all`` | ``any``).

    Returns ``(group_holds, audit_records, matched_ids)``.
    """
    logic = group.get("logic", "any")
    conditions = group.get("conditions", [])
    records = [_evaluate_condition(c, context) for c in conditions]
    matched_ids = [r["id"] for r in records if r["matched"]]

    if logic == "all":
        holds = len(conditions) > 0 and len(matched_ids) == len(conditions)
    elif logic == "any":
        holds = len(matched_ids) > 0
    else:
        raise ValueError(f"Unsupported group logic: {logic!r}")
    return holds, records, matched_ids


def _blocklist_hits(blocklist: dict[str, Any], context: RemediationContext) -> list[str]:
    """Return the blocklisted action identifiers present in the context."""
    actions = set(blocklist.get("actions", []))
    candidates: list[str] = []
    if context.action:
        candidates.append(context.action)
    candidates.extend(context.action_keywords)
    return [c for c in candidates if c in actions]


def route(
    context: RemediationContext | dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> SafetyRoutingDecision:
    """Route a remediation to its safe execution path.

    Args:
        context: A :class:`RemediationContext` (or a mapping of its fields).
        policy: Optional pre-loaded safety policy; defaults to the cached
            ``safety_rules.json`` from :func:`load_policy`.

    Returns:
        A :class:`SafetyRoutingDecision` with the chosen path and a full audit
        trail of every condition evaluated and which ones matched.
    """
    if isinstance(context, dict):
        context = RemediationContext(**context)
    if policy is None:
        policy = load_policy("safety_rules")

    auto_fix_group = policy.get("auto_fix_conditions", {})
    approval_group = policy.get("approval_conditions", {})
    escalation_group = policy.get("escalation_conditions", {})
    blocklist = policy.get("blocklist", {})

    # Evaluate every group up front so the audit trail is complete regardless of
    # which precedence branch ultimately decides the path.
    auto_fix_holds, auto_fix_records, auto_fix_matched = _evaluate_group(
        auto_fix_group, context
    )
    approval_holds, approval_records, approval_matched = _evaluate_group(
        approval_group, context
    )
    escalation_holds, escalation_records, escalation_matched = _evaluate_group(
        escalation_group, context
    )
    blocklist_hits = _blocklist_hits(blocklist, context)

    evaluated_conditions: dict[str, list[dict[str, Any]]] = {
        "blocklist": [
            {"id": "blocklist_action", "action": a, "matched": True}
            for a in blocklist_hits
        ],
        "escalation_conditions": escalation_records,
        "approval_conditions": approval_records,
        "auto_fix_conditions": auto_fix_records,
    }

    rollback_available = (
        context.rollback_note is not None and context.rollback_note != ""
    )

    # --- precedence ----------------------------------------------------------
    execution_path: ExecutionPath
    reasons: list[str]
    matched_conditions: list[str]

    if str(context.risk_level).lower() == "critical":
        execution_path = "human_escalation_required"
        reasons = ["risk_level is critical: always escalate to a human expert"]
        matched_conditions = ["risk_level_critical"]
    elif blocklist_hits:
        execution_path = "human_escalation_required"
        reasons = [
            f"action '{a}' is on the hard blocklist and must never auto-execute"
            for a in blocklist_hits
        ]
        matched_conditions = ["blocklist_action"]
    elif escalation_holds:
        execution_path = "human_escalation_required"
        reasons = [f"escalation condition '{c}' holds" for c in escalation_matched]
        matched_conditions = list(escalation_matched)
    elif approval_holds:
        execution_path = "user_approval_required"
        reasons = [f"approval condition '{c}' holds" for c in approval_matched]
        matched_conditions = list(approval_matched)
    elif auto_fix_holds:
        execution_path = "auto_fix"
        reasons = [
            "all auto-fix safety conditions hold: "
            + ", ".join(auto_fix_matched)
        ]
        matched_conditions = list(auto_fix_matched)
    else:
        execution_path = "user_approval_required"
        reasons = [
            "not eligible for auto-fix and no escalation condition holds; "
            "defaulting to user approval"
        ]
        matched_conditions = []

    blocklisted_action = blocklist_hits[0] if blocklist_hits else None
    why_safe = "; ".join(reasons)

    decision = SafetyRoutingDecision(
        execution_path=execution_path,
        approval_required=execution_path != "auto_fix",
        rollback_available=rollback_available,
        why_safe=why_safe,
        reasons=reasons,
        matched_conditions=matched_conditions,
        blocklisted=bool(blocklist_hits),
        blocklisted_action=blocklisted_action,
        evaluated_conditions=evaluated_conditions,
    )
    logger.debug(
        "Safety route -> %s (risk=%s env=%s matched=%s)",
        execution_path,
        context.risk_level,
        context.environment,
        matched_conditions,
    )
    return decision


def build_remediation_context(
    recommendation: Any,
    workload: Any | None = None,
    action_properties: dict[str, Any] | None = None,
) -> RemediationContext:
    """Assemble a :class:`RemediationContext` from pipeline objects.

    Pulls the environment / criticality from the ``Workload``, the risk level and
    ``rollback_note`` from the ``Recommendation``, and the concrete safety facts
    (reversibility, data sensitivity, etc.) from ``action_properties`` — the
    per-action metadata produced by the runbook layer (task 5.3).

    ``action_properties`` may also override any base field (it is applied last),
    which keeps this helper flexible for callers and tests that already know the
    full safety context.
    """
    rec = _as_dict(recommendation)
    wl = _as_dict(workload)
    props = dict(action_properties or {})

    data: dict[str, Any] = {}

    if "environment" in wl:
        data["environment"] = wl["environment"]
    if "workflow_criticality" in wl:
        data["workflow_criticality"] = wl["workflow_criticality"]

    if "risk_level" in rec:
        data["risk_level"] = rec["risk_level"]
    if rec.get("rollback_note") is not None:
        data["rollback_note"] = rec["rollback_note"]

    # Default the blocklist action identifier and keywords from the rec.
    keywords = [
        v
        for v in (
            rec.get("recommendation_type"),
            rec.get("action_category"),
            rec.get("recommended_action"),
        )
        if v
    ]
    if keywords:
        data.setdefault("action", keywords[0])
        data.setdefault("action_keywords", keywords)

    # action_properties wins: it carries the authoritative per-action safety
    # facts and may explicitly set the blocklist action.
    data.update(props)
    return RemediationContext(**data)


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
    raise TypeError(f"Cannot build a context from {type(obj)!r}")
