"""Tests for the missing-monitoring detection + NBA path (task 18.1).

Covers Requirements 3.1 (DET-MON-001 classification), 5.1 (RULE-MON-001 maps an
Issue to exactly one Recommendation), and 19.1 (the missing-monitoring scenario
flows through the pipeline).

The detection rule ``DET-MON-001`` flags a workload whose telemetry reports
``monitoring_enabled == false`` as a ``no_monitoring`` issue in the
``monitoring`` category. The NBA rule ``RULE-MON-001`` then produces an
``enable_monitoring`` recommendation that auto-fixes on non-production
workloads and requires approval on production. Both rules are config-driven
(``rules/detection_rules.json`` / ``rules/recommendation_rules.json``) and
evaluated by the existing generic engines; these tests assert the path end to
end without introducing any parallel mechanism.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone

import pytest

# --- Configure an isolated temp DB BEFORE importing services -----------------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_missing_monitoring_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from backend.core.database import init_db  # noqa: E402
from backend.modules.detection_insight import (  # noqa: E402
    assign_severity,
    classify,
    evaluate_rules,
)
from backend.modules.detection_insight import detector  # noqa: E402
from backend.modules.next_best_action import (  # noqa: E402
    build_draft,
    match_rule,
    recommend,
)
from backend.schemas.recommendation import Recommendation  # noqa: E402
from backend.schemas.telemetry import TelemetrySnapshot  # noqa: E402
from backend.schemas.workload import Workload  # noqa: E402
from backend.services import workload_service  # noqa: E402

_VALID_SEVERITIES = {"low", "medium", "high", "critical"}
_VALID_MODES = {"auto_fix", "user_approval_required", "human_escalation_required"}


@pytest.fixture(scope="module", autouse=True)
def _db():
    """Initialise the isolated temp DB schema once for this module."""
    init_db(_TMP_DB)
    yield
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


# --- Helpers -----------------------------------------------------------------
def _telemetry(workload_id: str, *, monitoring_enabled: bool) -> TelemetrySnapshot:
    """A healthy snapshot except for the monitoring flag under test."""
    return TelemetrySnapshot(
        workload_id=workload_id,
        cpu_usage_percent=45.0,
        memory_usage_percent=55.0,
        storage_gb=100.0,
        runtime_hours_24h=8.0,
        request_count_24h=50000,
        error_rate_percent=0.4,
        latency_ms=120.0,
        public_exposure=False,
        public_storage=False,
        vulnerability_severity="none",
        critical_vulnerability_count=0,
        access_anomaly_detected=False,
        monitoring_enabled=monitoring_enabled,
        cost_per_hour=0.5,
        cost_24h=12.0,
        cost_30d_forecast=360.0,
        energy_kwh_24h=14.0,
        carbon_kgco2e_24h=5.6,
        carbon_intensity_gco2_per_kwh=400.0,
        timestamp=datetime.now(timezone.utc),
    )


def _workload(workload_id: str, *, environment: str) -> Workload:
    return Workload(
        workload_id=workload_id,
        workload_name="Monitoring Test Workload",
        workload_type="background worker",
        cloud_service_type="container",
        environment=environment,
        region="us-east-1",
        owner_team="platform-team",
        construction_workflow="reporting_worker",
        workflow_criticality="low",
        status="healthy",
    )


# --- Detection: DET-MON-001 fires only when monitoring is disabled -----------
def test_rule_fires_when_monitoring_disabled():
    telemetry = _telemetry("wl-mon-001", monitoring_enabled=False)
    workload = _workload("wl-mon-001", environment="development")

    matches = evaluate_rules(telemetry, workload)
    rule_ids = {m.rule_id for m in matches}

    assert "DET-MON-001" in rule_ids
    # The monitoring-only payload is otherwise healthy -> exactly one rule fires.
    assert rule_ids == {"DET-MON-001"}

    match = next(m for m in matches if m.rule_id == "DET-MON-001")
    assert match.issue_type == "no_monitoring"
    assert match.issue_category == "monitoring"
    assert match.conditions_matched, "conditions_matched should not be empty"


def test_rule_does_not_fire_when_monitoring_enabled():
    telemetry = _telemetry("wl-mon-001", monitoring_enabled=True)
    workload = _workload("wl-mon-001", environment="development")

    matches = evaluate_rules(telemetry, workload)
    assert matches == [], (
        f"no rule should fire on a healthy monitored workload, got "
        f"{[m.rule_id for m in matches]}"
    )


def test_severity_keyed_by_environment():
    """DET-MON-001 hints: production -> high, non-production -> medium."""
    telemetry_prod = _telemetry("wl-mon-prod", monitoring_enabled=False)
    prod = _workload("wl-mon-prod", environment="production")
    telemetry_dev = _telemetry("wl-mon-dev", monitoring_enabled=False)
    dev = _workload("wl-mon-dev", environment="development")

    prod_match = classify(telemetry_prod, prod)
    dev_match = classify(telemetry_dev, dev)
    assert prod_match is not None and dev_match is not None

    prod_assessment = assign_severity(prod_match, prod)
    dev_assessment = assign_severity(dev_match, dev)

    assert prod_assessment.severity == "high"
    assert dev_assessment.severity == "medium"
    assert prod_assessment.severity in _VALID_SEVERITIES
    assert 0.0 <= dev_assessment.confidence_score <= 1.0


# --- Detection: full pipeline produces a well-formed Issue -------------------
def test_detect_produces_no_monitoring_issue():
    telemetry = _telemetry("wl-mon-detect", monitoring_enabled=False)
    workload = _workload("wl-mon-detect", environment="development")
    workload_service.upsert_workload(workload, db_path=_TMP_DB)

    issue = detector.detect(telemetry, workload, db_path=_TMP_DB)
    assert issue is not None, "missing monitoring should produce an Issue"

    assert issue["issue_type"] == "no_monitoring"
    assert issue["issue_category"] == "monitoring"
    assert issue["workload_id"] == "wl-mon-detect"
    assert issue["severity"] in _VALID_SEVERITIES
    assert 0.0 <= issue["confidence_score"] <= 1.0

    # Detection output structure is complete.
    assert issue["ml_result"] is not None
    assert issue["xai_explanation"] is not None
    assert isinstance(issue["llm_user_explanation"], str)
    assert issue["llm_user_explanation"]

    # The monitoring dimension carries the workflow-disruption risk.
    assert issue["estimated_impact"]["workflow_disruption_risk"] in {
        "low",
        "medium",
        "high",
    }

    # DET-MON-001 is recorded in the evidence trail.
    assert "DET-MON-001" in issue["detected_evidence"]["matched_rules"]


def test_detect_returns_none_when_monitoring_enabled():
    telemetry = _telemetry("wl-mon-healthy", monitoring_enabled=True)
    workload = _workload("wl-mon-healthy", environment="development")

    assert detector.detect(telemetry, workload, db_path=_TMP_DB) is None


# --- NBA: RULE-MON-001 path --------------------------------------------------
def _make_no_monitoring_issue(workload_id: str, telemetry: TelemetrySnapshot):
    from backend.schemas.issue import (
        EstimatedImpact,
        Issue,
        MLResult,
        XAIExplanation,
        XAIFactor,
    )

    return Issue(
        issue_id=f"iss-{workload_id}",
        workload_id=workload_id,
        issue_type="no_monitoring",
        issue_category="monitoring",
        severity="medium",
        confidence_score=0.7,
        detected_evidence=telemetry.model_dump(),
        ml_result=MLResult(
            model_name="Isolation Forest", anomaly_score=-0.2, is_anomaly=False
        ),
        xai_explanation=XAIExplanation(
            method="SHAP-style feature contribution",
            top_contributing_factors=[
                XAIFactor(
                    feature="monitoring_enabled",
                    value="False",
                    impact="observability disabled",
                )
            ],
        ),
        llm_user_explanation="placeholder",
        estimated_impact=EstimatedImpact(
            cost_risk="low",
            energy_risk="low",
            carbon_risk="low",
            security_risk="low",
            workflow_disruption_risk="medium",
        ),
        status="new",
        detected_at=datetime.now(timezone.utc),
    )


def test_nba_matches_enable_monitoring_rule():
    telemetry = _telemetry("wl-mon-nba", monitoring_enabled=False)
    workload = _workload("wl-mon-nba", environment="development")
    issue = _make_no_monitoring_issue("wl-mon-nba", telemetry)

    match = match_rule(issue, workload=workload, telemetry=telemetry)
    assert match is not None
    assert match.rule_id == "RULE-MON-001"
    assert match.action_category == "monitoring"
    assert match.recommendation_type == "enable_monitoring"
    # The route auto-enables and falls back to a ticket: both tools declared.
    assert "enable_monitoring" in match.mcp_tools
    assert "create_ticket" in match.mcp_tools
    assert match.rollback_note is not None  # reversible -> auto-fix eligible


def test_nba_auto_fixes_in_non_production():
    telemetry = _telemetry("wl-mon-dev", monitoring_enabled=False)
    workload = _workload("wl-mon-dev", environment="development")
    issue = _make_no_monitoring_issue("wl-mon-dev", telemetry)

    draft = build_draft(issue, workload, telemetry=telemetry)
    assert draft is not None
    assert draft.risk_level == "low"
    assert draft.required_execution_mode == "auto_fix"
    assert draft.approval_required is False


def test_nba_requires_approval_in_production():
    telemetry = _telemetry("wl-mon-prod", monitoring_enabled=False)
    workload = _workload("wl-mon-prod", environment="production")
    issue = _make_no_monitoring_issue("wl-mon-prod", telemetry)

    draft = build_draft(issue, workload, telemetry=telemetry)
    assert draft is not None
    # Production never auto-fixes: route to approval (ticket / owner sign-off).
    assert draft.required_execution_mode == "user_approval_required"
    assert draft.approval_required is True


def test_recommend_produces_complete_recommendation():
    telemetry = _telemetry("wl-mon-rec", monitoring_enabled=False)
    workload = _workload("wl-mon-rec", environment="development")
    issue = _make_no_monitoring_issue("wl-mon-rec", telemetry)

    rec = recommend(issue, workload, telemetry=telemetry)
    assert isinstance(rec, Recommendation)
    assert rec.issue_id == issue.issue_id
    assert rec.workload_id == "wl-mon-rec"
    assert rec.action_category == "monitoring"
    assert rec.recommendation_type == "enable_monitoring"
    assert rec.rule_triggered.rule_id == "RULE-MON-001"
    assert rec.rule_triggered.conditions_matched
    assert rec.required_execution_mode in _VALID_MODES
    assert rec.approval_required == (rec.required_execution_mode != "auto_fix")
    assert "enable_monitoring" in rec.mcp_tools
