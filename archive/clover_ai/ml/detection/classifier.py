"""Rule-based issue classification + severity (ARCHITECTURE.md §5.5.2, §5.8).

Isolation Forest says *whether* a workload is abnormal; these rules say *what
kind* of issue it is. Thresholds are computed per workload as
baseline x multiplier (§6.11), with absolute floors guarding tiny baselines.
"""
from __future__ import annotations

import json
from functools import lru_cache

from ml.common import paths

_NON_PROD = {"development", "testing", "staging"}
_CARBON_TYPES = {"Batch Job", "BIM Processing Job", "Storage"}


@lru_cache(maxsize=1)
def _rules() -> dict:
    with open(paths.DETECTION_RULES, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _metric_baselines() -> dict:
    with open(paths.MOCK_DATA_DIR / "metric_baselines.json", encoding="utf-8") as f:
        return json.load(f)["baselines"]


def threshold(workload_id: str, metric: str) -> float:
    """baseline(workload, metric) x multiplier(metric), floored (§6.11)."""
    r = _rules()
    mult = r["multipliers"].get(metric, 1.0)
    floor = r["absolute_floors"].get(metric, 0.0)
    base = _metric_baselines().get(workload_id, {}).get(metric)
    if base is None:
        return floor
    return max(base * mult, floor)


def _severity(issue_type: str, t: dict) -> str:
    env = t.get("environment")
    prod = env == "production"
    crit = t.get("workflow_criticality") == "critical"
    if issue_type == "critical_exposed_vulnerability":
        return "critical" if prod else "high"
    if issue_type == "public_storage":
        if prod and (crit or t.get("access_anomaly_detected")):
            return "critical"
        return "high" if prod else "medium"
    if issue_type == "high_error_rate":
        return "high" if prod else "medium"
    if issue_type == "no_monitoring":
        return "high" if prod else "medium"
    if issue_type in ("idle_or_overprovisioned_workload", "carbon_heavy_workload",
                      "cost_spike_or_waste"):
        return "medium"
    return "medium"


def classify(t: dict) -> list[dict]:
    """Return matched detection rules as
    [{rule_id, issue_type, issue_category, severity}], in rule order."""
    wid = t.get("workload_id", "")
    floors = _rules()["absolute_floors"]
    matched: list[dict] = []

    def add(rule):
        matched.append({
            "rule_id": rule["rule_id"],
            "issue_type": rule["issue_type"],
            "issue_category": rule["issue_category"],
            "severity": _severity(rule["issue_type"], t),
        })

    by_id = {r["rule_id"]: r for r in _rules()["rules"]}

    # DET-SEC-001: public exposure + critical vulnerability
    if t.get("public_exposure") and t.get("vulnerability_severity") == "critical":
        add(by_id["DET-SEC-001"])
    # DET-SEC-002: public storage
    if t.get("public_storage"):
        add(by_id["DET-SEC-002"])
    # DET-COST-ENERGY-001: idle non-production
    if (t.get("cpu_usage_percent", 100) < floors["idle_cpu_usage_percent"]
            and t.get("runtime_hours_24h", 0) >= floors["idle_runtime_hours_24h"]
            and t.get("environment") in _NON_PROD
            and t.get("cost_30d_forecast", 0) > threshold(wid, "cost_30d_forecast")):
        add(by_id["DET-COST-ENERGY-001"])
    # DET-CARBON-001: carbon-heavy batch/reporting/BIM
    if (t.get("workload_type") in _CARBON_TYPES
            and t.get("carbon_kgco2e_24h", 0) > threshold(wid, "carbon_kgco2e_24h")
            and t.get("workflow_criticality") in ("low", "medium")):
        add(by_id["DET-CARBON-001"])
    # DET-MON-001: missing monitoring
    if t.get("monitoring_enabled") is False:
        add(by_id["DET-MON-001"])
    # DET-PERF-001: high error rate
    if t.get("error_rate_percent", 0) > threshold(wid, "error_rate_percent"):
        add(by_id["DET-PERF-001"])
    # DET-COST-001: cost spike + low/moderate utilization
    if (t.get("cost_30d_forecast", 0) > threshold(wid, "cost_30d_forecast")
            and t.get("cpu_usage_percent", 100) < floors["low_utilization_cpu_percent"]):
        add(by_id["DET-COST-001"])

    return matched


__all__ = ["classify", "threshold"]
