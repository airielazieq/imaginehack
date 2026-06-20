"""Detection orchestrator for Module 1 (task 3.5).

This module is the entry point of the platform's intelligence. It wires the
Module 1 components built in tasks 3.1-3.4 into a single pipeline:

    preprocessing
      -> Isolation Forest anomaly score        (isolation_forest.score_snapshot)
      -> SHAP / SHAP-style top factors          (shap_explainer.explain)
      -> rule-based issue classification        (rule_classifier.evaluate_rules)
      -> severity + confidence assignment       (severity_assigner.assign_severity)
      -> estimated impact                       (this module)
      -> LLM / template user explanation        (llm_explainer.generate_explanation)
      -> Issue object (persisted) + ISSUE_DETECTED event

Healthy case: if **no** rule fires, no Issue is produced. The rule classifier
is authoritative for *what* an issue is (SDD §4-5); the Isolation Forest's
anomaly score is computed and recorded on every Issue's ``ml_result`` for
explainability, but it never manufactures an Issue on its own (the demo model
is intentionally over-sensitive, so a model-only trigger would flag healthy
workloads). This guarantees every Issue is classified into one of the seven
defined types and that a healthy baseline produces no Issue.

Consolidation (Requirement 3.3 / design Property 4): when an open Issue already
exists for the same workload within a 5-minute window, the existing Issue is
updated in place (keeping the **maximum** severity and refreshing evidence,
explanations and timestamp) instead of creating a duplicate.

The detector subscribes to ``TELEMETRY_INGESTED`` events so the
mock-scenario -> telemetry -> detection flow runs end to end. Subscription is
idempotent (:func:`register_subscriptions`).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.core.event_bus import Event, EventType, event_bus
from backend.modules.detection_insight import (
    isolation_forest,
    llm_explainer,
    rule_classifier,
    severity_assigner,
    shap_explainer,
)
from backend.modules.detection_insight.rule_classifier import RuleMatch
from backend.schemas.issue import (
    EstimatedImpact,
    Issue,
    MLResult,
    XAIExplanation,
)
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload
from backend.services import issue_service, telemetry_service, workload_service

logger = logging.getLogger("clover.detection.detector")


# --------------------------------------------------------------------------- #
# Estimated impact
# --------------------------------------------------------------------------- #
# Map a severity to one of the three EstimatedImpact risk levels.
_SEVERITY_TO_RISK: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "critical": "high",
}


def _risk_from_severity(severity: str) -> str:
    return _SEVERITY_TO_RISK.get(severity, "medium")


def _estimate_impact(issue_category: str, severity: str) -> EstimatedImpact:
    """Derive a per-dimension :class:`EstimatedImpact` from the classification.

    The dimension matching the issue category carries the severity-derived risk
    level; the remaining dimensions default to ``low``. ``cost_energy_carbon``
    raises all three GreenOps/cost dimensions together.
    """
    base = _risk_from_severity(severity)
    impact = {
        "cost_risk": "low",
        "energy_risk": "low",
        "carbon_risk": "low",
        "security_risk": "low",
        "workflow_disruption_risk": "low",
    }

    if issue_category == "security":
        impact["security_risk"] = base
        impact["workflow_disruption_risk"] = base
    elif issue_category == "cost":
        impact["cost_risk"] = base
    elif issue_category == "energy":
        impact["energy_risk"] = base
    elif issue_category == "carbon":
        impact["carbon_risk"] = base
    elif issue_category == "cost_energy_carbon":
        impact["cost_risk"] = base
        impact["energy_risk"] = base
        impact["carbon_risk"] = base
    elif issue_category == "performance":
        impact["workflow_disruption_risk"] = base
    elif issue_category == "monitoring":
        impact["workflow_disruption_risk"] = base

    return EstimatedImpact(**impact)


# --------------------------------------------------------------------------- #
# Evidence assembly
# --------------------------------------------------------------------------- #
def _build_evidence(
    telemetry: TelemetrySnapshot,
    matches: list[RuleMatch],
    ml_result: MLResult,
    xai: XAIExplanation,
) -> dict[str, Any]:
    """Assemble the ``detected_evidence`` dict carried on the Issue."""
    rule_evidence: dict[str, Any] = {}
    conditions_matched: list[str] = []
    matched_rule_ids: list[str] = []
    for match in matches:
        matched_rule_ids.append(match.rule_id)
        conditions_matched.extend(match.conditions_matched)
        rule_evidence.update(match.evidence)

    return {
        "matched_rules": matched_rule_ids,
        "conditions_matched": conditions_matched,
        "rule_evidence": rule_evidence,
        "anomaly_score": ml_result.anomaly_score,
        "is_anomaly": ml_result.is_anomaly,
        "model_name": ml_result.model_name,
        "top_factors": [
            {"feature": f.feature, "value": f.value, "impact": f.impact}
            for f in xai.top_contributing_factors
        ],
    }


def _top_evidence_for_explanation(xai: XAIExplanation) -> list:
    """Build the top-evidence sequence handed to the LLM/template explainer."""
    return [
        (f.feature, f.value, f.impact) for f in xai.top_contributing_factors[:3]
    ]


# --------------------------------------------------------------------------- #
# Workload context resolution
# --------------------------------------------------------------------------- #
def _resolve_workload(workload_id: str, workload: Workload | dict | None) -> Workload | None:
    """Coerce/lookup a :class:`Workload` for the detection context."""
    if isinstance(workload, Workload):
        return workload
    raw = workload
    if raw is None:
        raw = workload_service.get_workload(workload_id)
    if raw is None:
        return None
    try:
        return Workload(**raw)
    except Exception:  # noqa: BLE001 - malformed workload context is non-fatal
        logger.warning("Could not build Workload for %s; proceeding without context", workload_id)
        return None


# --------------------------------------------------------------------------- #
# Core detection
# --------------------------------------------------------------------------- #
def detect(
    telemetry: TelemetrySnapshot,
    workload: Workload | dict | None = None,
    *,
    db_path: str | None = None,
) -> dict | None:
    """Run the full detection pipeline for a single telemetry snapshot.

    Returns the persisted issue dict (newly created or consolidated), or
    ``None`` when the workload is healthy (no rule fired and not anomalous).
    """
    wl = _resolve_workload(telemetry.workload_id, workload)

    # 1. Isolation Forest anomaly score (+ SHAP factors) for explainability.
    #    The model's anomaly flag enriches the recorded ml_result but does NOT
    #    by itself create an Issue: the rule classifier is authoritative for
    #    *what* the issue is (SDD §4-5). This keeps every Issue classified into
    #    one of the seven defined types and prevents the over-sensitive model
    #    from manufacturing issues on healthy workloads.
    ml_result = isolation_forest.score_snapshot(telemetry, wl)
    xai = shap_explainer.explain(telemetry, wl)

    # 2. Rule-based classification.
    matches = rule_classifier.evaluate_rules(telemetry, wl)

    # 3. Healthy short-circuit: no rule fired -> nothing to report. (When no
    #    rule fires and the model is also not anomalous the workload is plainly
    #    healthy; when no rule fires but the model flags an anomaly we still
    #    have no classifiable issue, so we record nothing and let rules remain
    #    the source of truth.)
    if not matches:
        logger.debug(
            "Workload %s healthy (no detection rules fired)",
            telemetry.workload_id,
        )
        return None

    # 4. Determine classification + severity from the highest-severity rule
    #    (ties broken by policy declaration order).
    primary, primary_assessment = _select_primary(matches, wl)
    issue_type = primary.issue_type
    issue_category = primary.issue_category
    severity = primary_assessment.severity
    confidence = primary_assessment.confidence_score

    evidence = _build_evidence(telemetry, matches, ml_result, xai)

    # 5. LLM / template user-facing explanation (wording only).
    llm_explanation = llm_explainer.generate_explanation(
        issue_type=issue_type,
        top_evidence=_top_evidence_for_explanation(xai),
        impact_area=issue_category,
    )

    estimated_impact = _estimate_impact(issue_category, severity)

    # 6. Consolidate or create.
    existing = issue_service.find_open_issue(telemetry.workload_id, db_path=db_path)
    if existing is not None:
        return _consolidate(
            existing=existing,
            issue_type=issue_type,
            issue_category=issue_category,
            severity=severity,
            confidence=confidence,
            evidence=evidence,
            ml_result=ml_result,
            xai=xai,
            llm_explanation=llm_explanation,
            estimated_impact=estimated_impact,
            db_path=db_path,
        )

    issue = Issue(
        issue_id=f"iss-{uuid.uuid4().hex[:12]}",
        workload_id=telemetry.workload_id,
        issue_type=issue_type,
        issue_category=issue_category,
        severity=severity,
        confidence_score=confidence,
        detected_evidence=evidence,
        ml_result=ml_result,
        xai_explanation=xai,
        llm_user_explanation=llm_explanation,
        estimated_impact=estimated_impact,
        status="new",
        detected_at=datetime.now(timezone.utc),
    )
    issue_service.create_issue(issue, db_path=db_path)
    return issue.model_dump(mode="json")


def _select_primary(
    matches: list[RuleMatch], workload: Workload | None
) -> tuple[RuleMatch, severity_assigner.SeverityAssessment]:
    """Pick the highest-severity rule match (first by order on ties)."""
    best_match = matches[0]
    best_assessment = severity_assigner.assign_severity(best_match, workload=workload)
    for match in matches[1:]:
        assessment = severity_assigner.assign_severity(match, workload=workload)
        if issue_service.severity_rank(assessment.severity) > issue_service.severity_rank(
            best_assessment.severity
        ):
            best_match, best_assessment = match, assessment
    return best_match, best_assessment


def _consolidate(
    *,
    existing: dict,
    issue_type: str,
    issue_category: str,
    severity: str,
    confidence: float,
    evidence: dict,
    ml_result: MLResult,
    xai: XAIExplanation,
    llm_explanation: str,
    estimated_impact: EstimatedImpact,
    db_path: str | None,
) -> dict:
    """Merge a new detection into an existing open issue (max severity wins)."""
    existing_severity = existing.get("severity", "low")
    final_severity = issue_service.max_severity(existing_severity, severity)

    # When the new finding is at least as severe, adopt its classification and
    # explanations; otherwise keep the existing (more severe) classification but
    # still refresh evidence/timestamp.
    new_is_dominant = issue_service.severity_rank(severity) >= issue_service.severity_rank(
        existing_severity
    )

    if new_is_dominant:
        final_type = issue_type
        final_category = issue_category
        final_xai = xai
        final_llm = llm_explanation
        final_impact = estimated_impact
        final_confidence = max(confidence, existing.get("confidence_score", 0.0))
    else:
        final_type = existing.get("issue_type", issue_type)
        final_category = existing.get("issue_category", issue_category)
        final_xai = XAIExplanation(**existing["xai_explanation"])
        final_llm = existing.get("llm_user_explanation", llm_explanation)
        final_impact = EstimatedImpact(**existing["estimated_impact"])
        final_confidence = existing.get("confidence_score", confidence)

    # Record consolidation provenance in the evidence trail.
    merged_evidence = dict(evidence)
    merged_evidence["consolidated"] = True
    merged_evidence["consolidated_into"] = existing["issue_id"]
    prior = existing.get("detected_evidence", {})
    prior_rules = prior.get("matched_rules", []) if isinstance(prior, dict) else []
    merged_evidence["prior_matched_rules"] = prior_rules

    consolidated = Issue(
        issue_id=existing["issue_id"],
        workload_id=existing["workload_id"],
        issue_type=final_type,
        issue_category=final_category,
        severity=final_severity,
        confidence_score=final_confidence,
        detected_evidence=merged_evidence,
        ml_result=ml_result,
        xai_explanation=final_xai,
        llm_user_explanation=final_llm,
        estimated_impact=final_impact,
        status=existing.get("status", "new"),
        detected_at=datetime.now(timezone.utc),
    )
    issue_service.update_issue(consolidated, db_path=db_path)
    logger.info(
        "Consolidated detection into issue %s (severity %s -> %s)",
        existing["issue_id"],
        existing_severity,
        final_severity,
    )
    return consolidated.model_dump(mode="json")


async def detect_and_emit(
    telemetry: TelemetrySnapshot,
    workload: Workload | dict | None = None,
    *,
    correlation_id: str | None = None,
    db_path: str | None = None,
) -> dict | None:
    """Run :func:`detect` and publish ``ISSUE_DETECTED`` when an issue results."""
    issue = detect(telemetry, workload, db_path=db_path)
    if issue is None:
        return None
    payload = {
        "workload_id": issue["workload_id"],
        "issue_id": issue["issue_id"],
        "issue": issue,
    }
    event = Event(event_type=EventType.ISSUE_DETECTED, payload=payload)
    if correlation_id:
        event.correlation_id = correlation_id
    await event_bus.publish(event)
    return issue


# --------------------------------------------------------------------------- #
# Run helpers (used by the API)
# --------------------------------------------------------------------------- #
def _latest_snapshot(workload_id: str, *, db_path: str | None = None) -> TelemetrySnapshot | None:
    history = telemetry_service.get_telemetry_history(workload_id, limit=1, db_path=db_path)
    if not history:
        return None
    try:
        return TelemetrySnapshot(**history[0])
    except Exception:  # noqa: BLE001
        logger.exception("Latest telemetry for %s is invalid", workload_id)
        return None


async def run_for_workload(workload_id: str, *, db_path: str | None = None) -> dict | None:
    """Run detection on a workload's latest telemetry. Returns the issue or None."""
    snapshot = _latest_snapshot(workload_id, db_path=db_path)
    if snapshot is None:
        return None
    workload = workload_service.get_workload(workload_id, db_path=db_path)
    return await detect_and_emit(snapshot, workload, db_path=db_path)


async def run_all(*, db_path: str | None = None) -> list[dict]:
    """Run detection across every workload's latest telemetry.

    Returns the list of issues produced (created or consolidated); healthy
    workloads contribute nothing.
    """
    issues: list[dict] = []
    for workload in workload_service.list_workloads(db_path=db_path):
        workload_id = workload["workload_id"]
        result = await run_for_workload(workload_id, db_path=db_path)
        if result is not None:
            issues.append(result)
    return issues


# --------------------------------------------------------------------------- #
# Event subscription (idempotent)
# --------------------------------------------------------------------------- #
async def _on_telemetry_ingested(event: Event) -> None:
    """Event handler: run detection for an ingested telemetry snapshot."""
    payload = event.payload or {}
    raw_snapshot = payload.get("snapshot")
    if raw_snapshot is None:
        return
    try:
        snapshot = TelemetrySnapshot(**raw_snapshot)
    except Exception:  # noqa: BLE001
        logger.exception("TELEMETRY_INGESTED carried an invalid snapshot")
        return
    await detect_and_emit(snapshot, correlation_id=event.correlation_id)


_subscribed = False


def register_subscriptions() -> None:
    """Subscribe the detector to ``TELEMETRY_INGESTED`` (idempotent)."""
    global _subscribed
    if _subscribed:
        return
    event_bus.subscribe(EventType.TELEMETRY_INGESTED, _on_telemetry_ingested)
    _subscribed = True
    logger.info("Detection orchestrator subscribed to TELEMETRY_INGESTED")
