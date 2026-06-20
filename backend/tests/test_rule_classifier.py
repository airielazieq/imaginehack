"""Tests for the rule-based detection classifier and severity assigner (task 3.1).

Covers Requirements 3.1 (classify into one of the 7 defined issue types) and
3.2 (assign a severity in {low, medium, high, critical} and a confidence score
in [0, 1]).

The core scenario assertions drive the classifier with the 7 demo payloads from
``mock_data/scenario_payloads.json`` (with workload context loaded from
``sample_workloads.json``) and verify each triggers exactly its documented
``expected_detection_rule`` / ``expected_issue_type``. The healthy baseline must
trigger nothing.
"""

from __future__ import annotations

import json

import pytest

from backend.core.config import MOCK_DATA_DIR, load_policy
from backend.modules.detection_insight import (
    RuleMatch,
    assign_severity,
    classify,
    evaluate_rules,
)
from backend.modules.detection_insight.rule_classifier import build_context
from backend.schemas.issue import Issue  # noqa: F401  (severity literal reference)
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload

_VALID_SEVERITIES = {"low", "medium", "high", "critical"}
_DEFINED_ISSUE_TYPES = {
    "public_storage",
    "critical_exposed_vulnerability",
    "idle_or_overprovisioned_workload",
    "carbon_heavy_workload",
    "no_monitoring",
    "high_error_rate",
    "cost_spike_or_waste",
}


# --- Fixtures / loaders ------------------------------------------------------
def _load_json(name: str):
    with (MOCK_DATA_DIR / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def workloads_by_id() -> dict[str, Workload]:
    raw = _load_json("sample_workloads.json")
    return {w["workload_id"]: Workload(**w) for w in raw}


@pytest.fixture(scope="module")
def scenarios() -> list[dict]:
    return _load_json("scenario_payloads.json")["scenarios"]


@pytest.fixture(scope="module")
def baselines() -> list[dict]:
    return _load_json("healthy_baseline.json")


# --- Scenario-driven classification (Requirement 3.1) ------------------------
def test_each_scenario_triggers_its_expected_rule(scenarios, workloads_by_id):
    assert len(scenarios) == 7
    for scenario in scenarios:
        telemetry = TelemetrySnapshot(**scenario["telemetry"])
        workload = workloads_by_id[scenario["target_workload_id"]]

        matches = evaluate_rules(telemetry, workload)
        matched_rule_ids = [m.rule_id for m in matches]

        # The scenarios are engineered to trigger exactly one rule.
        assert len(matches) == 1, (
            f"{scenario['scenario_id']} expected one rule, got {matched_rule_ids}"
        )

        match = matches[0]
        assert match.rule_id == scenario["expected_detection_rule"], (
            f"{scenario['scenario_id']}: expected {scenario['expected_detection_rule']}, "
            f"got {match.rule_id}"
        )
        assert match.issue_type == scenario["expected_issue_type"]
        assert match.issue_type in _DEFINED_ISSUE_TYPES
        assert match.conditions_matched, "conditions_matched should not be empty"


def test_each_scenario_severity_and_confidence_valid(scenarios, workloads_by_id):
    """Requirement 3.2: severity in the defined set, confidence in [0, 1]."""
    for scenario in scenarios:
        telemetry = TelemetrySnapshot(**scenario["telemetry"])
        workload = workloads_by_id[scenario["target_workload_id"]]

        match = classify(telemetry, workload)
        assert match is not None

        assessment = assign_severity(match, workload)
        assert assessment.severity in _VALID_SEVERITIES
        assert 0.0 <= assessment.confidence_score <= 1.0


def test_healthy_baseline_triggers_no_rules(baselines, workloads_by_id):
    for snapshot in baselines:
        telemetry = TelemetrySnapshot(**snapshot)
        workload = workloads_by_id[snapshot["workload_id"]]
        matches = evaluate_rules(telemetry, workload)
        assert matches == [], (
            f"healthy baseline for {snapshot['workload_id']} should not fire "
            f"any rule, got {[m.rule_id for m in matches]}"
        )


# --- Operator coverage (unit) ------------------------------------------------
def _base_telemetry(**overrides) -> dict:
    base = {
        "workload_id": "wl-test-001",
        "cpu_usage_percent": 50.0,
        "memory_usage_percent": 50.0,
        "storage_gb": 10.0,
        "runtime_hours_24h": 5.0,
        "request_count_24h": 100,
        "error_rate_percent": 0.1,
        "latency_ms": 100.0,
        "public_exposure": False,
        "public_storage": False,
        "vulnerability_severity": "none",
        "critical_vulnerability_count": 0,
        "access_anomaly_detected": False,
        "monitoring_enabled": True,
        "cost_per_hour": 1.0,
        "cost_24h": 24.0,
        "cost_30d_forecast": 100.0,
        "energy_kwh_24h": 10.0,
        "carbon_kgco2e_24h": 4.0,
        "carbon_intensity_gco2_per_kwh": 400.0,
        "timestamp": "2026-01-15T09:00:00Z",
    }
    base.update(overrides)
    return base


def test_eq_operator_boolean_match():
    telemetry = TelemetrySnapshot(**_base_telemetry(public_storage=True))
    matches = evaluate_rules(telemetry)  # no workload needed for DET-SEC-001
    assert "DET-SEC-001" in {m.rule_id for m in matches}


def test_numeric_lt_gte_neq_combination_requires_workload_context():
    # DET-COST-001: cpu < 10 AND runtime >= 20 AND environment != production.
    telemetry = TelemetrySnapshot(
        **_base_telemetry(cpu_usage_percent=4.0, runtime_hours_24h=22.0)
    )

    # Without workload context the environment field is missing -> no match.
    assert "DET-COST-001" not in {m.rule_id for m in evaluate_rules(telemetry)}

    dev_workload = {"environment": "development", "workflow_criticality": "low"}
    assert "DET-COST-001" in {m.rule_id for m in evaluate_rules(telemetry, dev_workload)}

    prod_workload = {"environment": "production", "workflow_criticality": "low"}
    assert "DET-COST-001" not in {m.rule_id for m in evaluate_rules(telemetry, prod_workload)}


def test_value_ref_in_operator_resolves_named_list():
    # DET-CARBON-001 uses value_ref into batch_workflows for construction_workflow.
    telemetry = TelemetrySnapshot(**_base_telemetry(carbon_kgco2e_24h=80.0))

    batch_wl = {"construction_workflow": "reporting_worker", "environment": "staging"}
    assert "DET-CARBON-001" in {m.rule_id for m in evaluate_rules(telemetry, batch_wl)}

    # A non-batch workflow should not match the value_ref list.
    interactive_wl = {
        "construction_workflow": "field_worker_mobile_app",
        "environment": "staging",
    }
    assert "DET-CARBON-001" not in {
        m.rule_id for m in evaluate_rules(telemetry, interactive_wl)
    }


# --- Severity assignment (unit) ----------------------------------------------
def test_severity_hint_keyed_by_environment():
    policy = load_policy("detection_rules")
    sec001 = next(r for r in policy["rules"] if r["id"] == "DET-SEC-001")
    match = RuleMatch(
        rule_id="DET-SEC-001",
        issue_type="public_storage",
        issue_category="security",
        conditions_matched=["public_storage eq True (actual=True)"],
        severity_hint=sec001["severity_hint"],
        conditions=sec001["conditions"],
        evidence={"public_storage": True},
    )

    prod = assign_severity(match, environment="production", workflow_criticality="low")
    nonprod = assign_severity(match, environment="development", workflow_criticality="low")

    assert prod.severity == "critical"  # production hint
    assert nonprod.severity == "high"   # non_production hint


def test_workflow_criticality_escalates_medium_baseline():
    # DET-COST-001 has a flat "default": "medium" hint.
    policy = load_policy("detection_rules")
    cost001 = next(r for r in policy["rules"] if r["id"] == "DET-COST-001")
    match = RuleMatch(
        rule_id="DET-COST-001",
        issue_type="idle_or_overprovisioned_workload",
        issue_category="cost_energy_carbon",
        conditions_matched=[],
        severity_hint=cost001["severity_hint"],
        conditions=cost001["conditions"],
        evidence={"cpu_usage_percent": 4.0, "runtime_hours_24h": 22.0},
    )

    low = assign_severity(match, environment="development", workflow_criticality="low")
    critical = assign_severity(
        match, environment="development", workflow_criticality="critical"
    )

    assert low.severity == "medium"
    assert critical.severity == "high"  # escalated one level


def test_confidence_in_unit_interval_and_specificity_orders():
    policy = load_policy("detection_rules")
    # Single-condition rule (DET-MON-001) vs three-condition rule (DET-COST-001).
    mon = next(r for r in policy["rules"] if r["id"] == "DET-MON-001")
    cost = next(r for r in policy["rules"] if r["id"] == "DET-COST-001")

    mon_match = RuleMatch(
        rule_id="DET-MON-001",
        issue_type="no_monitoring",
        issue_category="monitoring",
        conditions_matched=[],
        severity_hint=mon["severity_hint"],
        conditions=mon["conditions"],
        evidence={"monitoring_enabled": False},
    )
    cost_match = RuleMatch(
        rule_id="DET-COST-001",
        issue_type="idle_or_overprovisioned_workload",
        issue_category="cost_energy_carbon",
        conditions_matched=[],
        severity_hint=cost["severity_hint"],
        conditions=cost["conditions"],
        evidence={
            "cpu_usage_percent": 1.0,
            "runtime_hours_24h": 24.0,
            "environment": "development",
        },
    )

    mon_conf = assign_severity(mon_match, environment="development").confidence_score
    cost_conf = assign_severity(cost_match, environment="development").confidence_score

    assert 0.0 <= mon_conf <= 1.0
    assert 0.0 <= cost_conf <= 1.0
    # The more specific (3-condition) rule should be at least as confident.
    assert cost_conf >= mon_conf


def test_build_context_merges_workload_and_telemetry():
    telemetry = TelemetrySnapshot(**_base_telemetry())
    workload = {"environment": "staging", "construction_workflow": "reporting_worker"}
    ctx = build_context(telemetry, workload)
    assert ctx["environment"] == "staging"
    assert ctx["construction_workflow"] == "reporting_worker"
    # Telemetry value wins on collisions.
    assert ctx["workload_id"] == "wl-test-001"
