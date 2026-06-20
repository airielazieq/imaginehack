"""Tests for rule-grounded issue explanations (Finding #1 fix).

The detection pipeline runs the Isolation Forest + SHAP explainer for *anomaly*
context and a rule classifier for *classification*. Classification is
rule-authoritative (a rule firing is the reason an Issue exists), so the
user-facing "why" must come from the rule's matched conditions — not from the
anomaly model's incidental top SHAP factors, which for boolean/categorical
security findings (public exposure, critical CVE, missing monitoring) are
unrelated to the actual cause.

These tests pin that contract: the explanation for a rule-driven issue cites the
condition that fired, and never invents an unrelated carbon/cost narrative.
"""

from __future__ import annotations

from backend.modules.detection_insight import llm_explainer
from backend.modules.detection_insight.detector import (
    _rule_evidence_for_explanation,
)
from backend.modules.detection_insight.rule_classifier import RuleMatch


def _critical_vuln_match() -> RuleMatch:
    return RuleMatch(
        rule_id="DET-SEC-002",
        issue_type="critical_exposed_vulnerability",
        issue_category="security",
        conditions_matched=[
            "public_exposure eq True (actual=True)",
            "vulnerability_severity eq 'critical' (actual='critical')",
        ],
        evidence={"public_exposure": True, "vulnerability_severity": "critical"},
    )


def test_rule_evidence_cites_the_conditions_that_fired():
    """A security rule's 'why' references exposure + the vulnerability."""
    phrases = _rule_evidence_for_explanation(_critical_vuln_match())
    text = " ".join(phrases).lower()
    assert "expos" in text or "public" in text
    assert "vulnerab" in text


def test_rule_evidence_excludes_unrelated_anomaly_metrics():
    """The incoherent carbon/cost narrative must not appear for a vuln issue."""
    text = " ".join(_rule_evidence_for_explanation(_critical_vuln_match())).lower()
    assert "carbon" not in text
    assert "cost" not in text


def test_full_security_explanation_is_coherent():
    """End-to-end wording: subject and 'because' clause agree."""
    primary = _critical_vuln_match()
    explanation = llm_explainer.generate_explanation(
        issue_type=primary.issue_type,
        top_evidence=_rule_evidence_for_explanation(primary),
        impact_area=primary.issue_category,
    ).lower()
    assert "critical exposed vulnerability" in explanation
    assert ("expos" in explanation) or ("public" in explanation)
    assert "vulnerab" in explanation
    assert "carbon" not in explanation


def test_public_storage_explanation_cites_storage():
    primary = RuleMatch(
        rule_id="DET-SEC-001",
        issue_type="public_storage",
        issue_category="security",
        conditions_matched=["public_storage eq True (actual=True)"],
        evidence={"public_storage": True},
    )
    text = " ".join(_rule_evidence_for_explanation(primary)).lower()
    assert "storage" in text
    assert "public" in text or "accessible" in text


def test_missing_monitoring_explanation_cites_monitoring():
    primary = RuleMatch(
        rule_id="DET-MON-001",
        issue_type="no_monitoring",
        issue_category="monitoring",
        conditions_matched=["monitoring_enabled eq False (actual=False)"],
        evidence={"monitoring_enabled": False},
    )
    text = " ".join(_rule_evidence_for_explanation(primary)).lower()
    assert "monitoring" in text


def test_numeric_rule_evidence_includes_the_value():
    """Anomaly-style numeric rules keep coherent, value-bearing phrasing."""
    primary = RuleMatch(
        rule_id="DET-CARBON-001",
        issue_type="carbon_heavy_workload",
        issue_category="carbon",
        conditions_matched=["carbon_kgco2e_24h gt 10.0 (actual=18.5)"],
        evidence={"carbon_kgco2e_24h": 18.5},
    )
    text = " ".join(_rule_evidence_for_explanation(primary)).lower()
    assert "carbon" in text
    assert "18.5" in text


def test_evidence_is_capped_to_three_clauses():
    primary = RuleMatch(
        rule_id="X",
        issue_type="t",
        issue_category="cost",
        conditions_matched=[],
        evidence={"a": 1, "b": 2, "c": 3, "d": 4, "e": 5},
    )
    assert len(_rule_evidence_for_explanation(primary)) <= 3
