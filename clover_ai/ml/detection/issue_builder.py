"""Assemble the Structured Issue Object (ARCHITECTURE.md §9.2).

Orchestrates Module 1 end to end:
  Isolation Forest score  -> ml.isolation_forest.detector
  rule classification     -> ml.detection.classifier
  root-cause merge (§6.6) -> group matched rules, pick one primary issue
  SHAP-style factors      -> ml.explainability.shap_explainer
  LLM explanation         -> ml.llm.payloads (payload + deterministic fallback)

Returns a LIST of issue objects: usually one per workload, but genuinely
independent problems (e.g. a security exposure AND a cost-waste pattern) stay
separate per the §6.6 exception.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache

from ml.common import paths
from ml.detection import classifier
from ml.explainability import shap_explainer
from ml.isolation_forest import detector
from ml.llm import payloads

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

_EVIDENCE_FIELDS = [
    "cpu_usage_percent", "memory_usage_percent", "runtime_hours_24h",
    "error_rate_percent", "cost_24h", "cost_30d_forecast",
    "energy_kwh_24h", "carbon_kgco2e_24h", "public_exposure",
    "public_storage", "vulnerability_severity", "monitoring_enabled",
]


@lru_cache(maxsize=1)
def _rec_rules() -> dict:
    with open(paths.RECOMMENDATION_RULES, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _group_of() -> dict:
    """issue_type -> root_cause_group."""
    return {r["issue_type"]: r["root_cause_group"] for r in _rec_rules()["rules"]}


@lru_cache(maxsize=1)
def _primary_priority() -> list[str]:
    return _rec_rules()["merge_policy"]["primary_rule_priority"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _issue_category_for(issue_type: str, matched: list[dict]) -> str:
    for m in matched:
        if m["issue_type"] == issue_type:
            return m["issue_category"]
    return "cost_energy_carbon"


def _estimated_impact(issue_type: str, severity: str, t: dict) -> dict:
    lo, hi = "low", "high"
    base = {"cost_risk": lo, "energy_risk": lo, "carbon_risk": lo,
            "security_risk": lo, "workflow_disruption_risk": lo}
    if issue_type in ("idle_or_overprovisioned_workload", "cost_spike_or_waste"):
        base.update(cost_risk=hi, energy_risk="medium", carbon_risk="medium")
    elif issue_type == "carbon_heavy_workload":
        base.update(carbon_risk=hi, energy_risk=hi, cost_risk="medium")
    elif issue_type in ("public_storage", "critical_exposed_vulnerability"):
        base.update(security_risk="critical" if severity == "critical" else hi)
        if t.get("environment") == "production":
            base["workflow_disruption_risk"] = "medium"
    elif issue_type == "high_error_rate":
        base.update(workflow_disruption_risk=hi if t.get("environment") == "production" else "medium")
    elif issue_type == "no_monitoring":
        base.update(workflow_disruption_risk="medium")
    return base


def _confidence(ml_result: dict, matched_in_group: int) -> float:
    is_anom = ml_result.get("is_anomaly")
    if is_anom is True:
        conf = 0.9
    elif is_anom is False:
        conf = 0.7  # rules fired but model didn't flag -> still a real rule hit
    else:
        conf = 0.6  # model fallback
    conf += min(0.06, 0.02 * max(0, matched_in_group - 1))  # corroboration
    return round(min(conf, 0.98), 2)


def _build_one(t: dict, group_rules: list[dict], ml_result: dict, seq: int) -> dict:
    issue_types = [r["issue_type"] for r in group_rules]
    # Primary selection (§6.6): priority list first, then highest severity.
    prio = _primary_priority()
    rule_by_type = {r["issue_type"]: r for r in group_rules}

    def sort_key(r):
        try:
            p = prio.index(r["rule_id"]) if r["rule_id"] in prio else len(prio)
        except ValueError:
            p = len(prio)
        # also consider issue_type priority via mapped rec rule_id is not 1:1; keep simple
        return (p, -_SEVERITY_RANK.get(r["severity"], 0))

    # group_rules are detection rules; map to recommendation priority via issue_type
    rec_id_by_issue = {r["issue_type"]: r["rule_id"] for r in _rec_rules()["rules"]}

    def sort_key2(r):
        rec_id = rec_id_by_issue.get(r["issue_type"], "")
        p = prio.index(rec_id) if rec_id in prio else len(prio)
        return (p, -_SEVERITY_RANK.get(r["severity"], 0))

    primary = sorted(group_rules, key=sort_key2)[0]
    severity = max((r["severity"] for r in group_rules),
                   key=lambda s: _SEVERITY_RANK.get(s, 0))

    issue = {
        "issue_id": f"iss-{seq:04d}",
        "workload_id": t.get("workload_id"),
        "workload_name": t.get("workload_name"),
        "workload_type": t.get("workload_type"),
        "environment": t.get("environment"),
        "region": t.get("region"),
        "owner_team": t.get("owner_team"),
        "workflow_criticality": t.get("workflow_criticality"),
        "issue_type": primary["issue_type"],
        "issue_category": primary["issue_category"],
        "severity": severity,
        "confidence_score": _confidence(ml_result, len(group_rules)),
        "detected_evidence": {f: t.get(f) for f in _EVIDENCE_FIELDS if f in t},
        "detection_rules": {
            "primary_rule_id": primary["rule_id"],
            "contributing_rule_ids": [r["rule_id"] for r in group_rules
                                      if r["rule_id"] != primary["rule_id"]],
            "contributing_issue_types": [it for it in issue_types
                                         if it != primary["issue_type"]],
        },
        "ml_result": ml_result,
        "xai_explanation": shap_explainer.explain(t),
        "estimated_impact": _estimated_impact(primary["issue_type"], severity, t),
        "status": "new",
        "detected_at": _now(),
    }
    issue["llm_user_explanation"] = payloads.render_issue_explanation_fallback(issue)
    issue["llm_payload"] = payloads.build_issue_payload(issue)
    return issue


def detect(telemetry: dict, start_seq: int = 1) -> list[dict]:
    """Run Module 1 on one telemetry snapshot. Returns 0+ issue objects."""
    ml_result = detector.score(telemetry)
    matched = classifier.classify(telemetry)
    if not matched:
        return []

    groups: dict[str, list[dict]] = {}
    for m in matched:
        g = _group_of().get(m["issue_type"], m["issue_type"])
        groups.setdefault(g, []).append(m)

    issues = []
    seq = start_seq
    # Stable order: most severe group first.
    for _, group_rules in sorted(
        groups.items(),
        key=lambda kv: -max(_SEVERITY_RANK.get(r["severity"], 0) for r in kv[1]),
    ):
        issues.append(_build_one(telemetry, group_rules, ml_result, seq))
        seq += 1
    return issues


__all__ = ["detect"]
