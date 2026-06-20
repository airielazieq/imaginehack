"""Next Best Action recommendation builder (ARCHITECTURE.md §6, §9.3).

Maps a Structured Issue Object to a Structured Recommendation Object using the
rule-based engine in rules/recommendation_rules.json, attaches the XGBoost
optimization impact forecast, and proposes risk_level + required_execution_mode.

Scope note: the AI/Mock-Data subteam owns the forecast and the rule config.
The final, authoritative safety decision (Module 3, §13) is the SE backend's
safety engine — the execution_mode here is the rule-recommended value it consumes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache

from ml.common import paths
from ml.llm import payloads
from ml.xgboost_forecast import forecaster

_NON_PROD = {"development", "testing", "staging"}


@lru_cache(maxsize=1)
def _rules_by_issue() -> dict:
    with open(paths.RECOMMENDATION_RULES, encoding="utf-8") as f:
        rules = json.load(f)["rules"]
    return {r["issue_type"]: r for r in rules}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _execution_mode(rule: dict, issue: dict) -> str:
    env = issue.get("environment", "production")
    mode = rule["execution_mode_by_environment"].get(env, "user_approval_required")
    # Sensitive production storage never blind auto-fixes (§13.4/§13.5).
    if rule.get("sensitive_data_forces_escalation") and env == "production":
        mode = "human_escalation_required"
    return mode


def _risk_level(issue: dict, mode: str) -> str:
    """ARCHITECTURE.md §6.7."""
    env = issue.get("environment")
    crit = issue.get("workflow_criticality")
    category = issue.get("issue_category")
    if category == "security":
        if env == "production":
            return "critical"
        return "high"
    if env == "production":
        return "high"
    if env == "staging":
        return "medium"
    if env in _NON_PROD:
        return "low" if crit in ("low", "medium") else "medium"
    return "medium"


def recommend(issue: dict, seq: int = 1) -> dict | None:
    """Build a Structured Recommendation Object (§9.3) for an issue."""
    rule = _rules_by_issue().get(issue["issue_type"])
    if rule is None:
        return None

    telemetry = dict(issue.get("detected_evidence", {}))
    telemetry.update({
        "workload_id": issue.get("workload_id"),
        "workload_type": issue.get("workload_type"),
        "environment": issue.get("environment"),
        "region": issue.get("region"),
        "workflow_criticality": issue.get("workflow_criticality"),
    })

    fc_result, impact = forecaster.optimization_impact(
        telemetry, rule["optimization_factors"])

    mode = _execution_mode(rule, issue)
    risk = _risk_level(issue, mode)

    rec = {
        "recommendation_id": f"rec-{seq:04d}",
        "issue_id": issue.get("issue_id"),
        "workload_id": issue.get("workload_id"),
        "workload_name": issue.get("workload_name"),
        "recommended_action": rule["recommended_action"],
        "action_category": rule["action_category"],
        "recommendation_type": rule["recommendation_type"],
        "rule_triggered": {
            "primary_rule_id": rule["rule_id"],
            "rule_name": rule["recommended_action"],
            "contributing_rule_ids": issue.get("detection_rules", {})
                                         .get("contributing_rule_ids", []),
            "merge_reason": (
                "Related cost/energy/carbon signals merged as impact evidence "
                "for one root cause (§6.6)."
                if issue.get("detection_rules", {}).get("contributing_rule_ids")
                else None
            ),
        },
        "forecast_model_result": fc_result,
        "optimization_impact_forecast": impact,
        "risk_level": risk,
        "required_execution_mode": mode,
        "approval_required": mode != "auto_fix",
        "rollback_note": rule["rollback_note"],
        "created_at": _now(),
    }
    rec["llm_recommendation_explanation"] = \
        payloads.render_recommendation_explanation_fallback(rec)
    rec["llm_payload"] = payloads.build_recommendation_payload(issue, rec)
    return rec


__all__ = ["recommend"]
