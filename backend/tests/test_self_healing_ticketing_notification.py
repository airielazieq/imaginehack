"""Tests for wiring the ticketing + notification connectors into self-healing
(task 18.2 — Requirements 10.1, 10.2).

These tests exercise the report generator's escalation path directly with the
*simulated* MCP connectors (no real I/O, no DB) and assert that:

* the human_escalation path opens a tracking ticket AND sends notifications,
  with every connector invocation recorded in ``mcp_tools_executed`` and an
  audit-trail entry that notes policy compliance, and
* the auto_fix path still works without regression and records the ticket /
  notification tools that belong to its runbook.

The connectors are deterministic and never sleep, so these tests run instantly.
"""

from __future__ import annotations


from backend.modules.self_healing import report_generator


# --------------------------------------------------------------------------- #
# Fixtures (plain dicts — no DB / pipeline needed)
# --------------------------------------------------------------------------- #
def _impact_forecast() -> dict:
    return {
        "forecast_without_action": {
            "cost_30d": 1000.0,
            "energy_30d_kwh": 500.0,
            "carbon_30d_kgco2e": 200.0,
        },
        "forecast_after_action": {
            "cost_30d": 600.0,
            "energy_30d_kwh": 300.0,
            "carbon_30d_kgco2e": 120.0,
        },
        "projected_savings": {
            "cost_30d": 400.0,
            "energy_30d_kwh": 200.0,
            "carbon_30d_kgco2e": 80.0,
        },
    }


def _escalation_recommendation() -> dict:
    """A critical production security recommendation -> human_escalation."""
    return {
        "recommendation_id": "rec-esc-18-2",
        "issue_id": "iss-esc-18-2",
        "workload_id": "wl-field-app-18-2",
        "recommended_action": "Restrict public access and patch the workload.",
        "action_category": "security",
        "recommendation_type": "restrict_access",
        "risk_level": "critical",
        "required_execution_mode": "human_escalation_required",
        "rollback_note": "Re-open access and restore the previous network policy.",
        "optimization_impact_forecast": _impact_forecast(),
    }


def _auto_fix_recommendation() -> dict:
    """A non-prod, reversible, non-security recommendation -> auto_fix."""
    return {
        "recommendation_id": "rec-auto-18-2",
        "issue_id": "iss-auto-18-2",
        "workload_id": "wl-ci-pipeline-18-2",
        "recommended_action": "Enable monitoring on the workload.",
        "action_category": "monitoring",
        "recommendation_type": "enable_monitoring",
        "risk_level": "low",
        "required_execution_mode": "auto_fix",
        "mcp_tools": ["enable_monitoring", "create_ticket"],
        "rollback_note": "Disable the newly enabled monitoring configuration.",
        "optimization_impact_forecast": _impact_forecast(),
    }


_ESC_WORKLOAD = {
    "workload_id": "wl-field-app-18-2",
    "workload_name": "Field App",
    "environment": "production",
    "workflow_criticality": "high",
    "owner_team": "field-ops-team",
}
_AUTO_WORKLOAD = {
    "workload_id": "wl-ci-pipeline-18-2",
    "workload_name": "CI/CD Pipeline",
    "environment": "development",
    "workflow_criticality": "medium",
    "owner_team": "devops-team",
}


def _tools_by_name(result: dict) -> dict[str, dict]:
    return {t["tool"]: t for t in result["mcp_tools_executed"]}


# --------------------------------------------------------------------------- #
# human_escalation path: ticket + notification + audit trail
# --------------------------------------------------------------------------- #
def test_escalation_creates_ticket_and_sends_notification():
    """The human_escalation path opens a ticket AND notifies, both recorded."""
    result = report_generator.generate_report(
        _escalation_recommendation(),
        _ESC_WORKLOAD,
        {
            "issue_type": "critical_exposed_vulnerability",
            "severity": "critical",
            "issue_category": "security",
        },
    ).model_dump(mode="json")

    assert result["execution_path"] == "human_escalation"
    assert result["execution_status"] == "escalated"

    tools = _tools_by_name(result)

    # A tracking ticket was created via the ticketing connector (Req 10.1) and
    # captured into the MCP executions with a concrete ticket id.
    assert "create_ticket" in tools
    ticket = tools["create_ticket"]
    assert ticket["category"] == "ticketing"
    assert ticket["status"] == "success"
    assert ticket["output"]["ticket_id"]
    # Full Issue / Recommendation context is carried on the ticket.
    assert ticket["input"]["recommendation_id"] == "rec-esc-18-2"
    assert ticket["input"]["issue_id"] == "iss-esc-18-2"

    # A notification was delivered via the notification connector (Req 10.2).
    assert "notify_owner" in tools
    owner = tools["notify_owner"]
    assert owner["category"] == "notification"
    assert owner["status"] == "success"
    assert owner["output"]["delivery_status"] == "delivered"
    assert owner["input"]["owner_team"] == "field-ops-team"

    # Security issues also page the security team.
    assert "notify_security_team" in tools
    assert tools["notify_security_team"]["category"] == "notification"


def test_escalation_records_audit_trail_with_policy_compliance():
    """The escalation records an audit-trail entry noting policy compliance."""
    result = report_generator.generate_report(
        _escalation_recommendation(),
        _ESC_WORKLOAD,
        {
            "issue_type": "critical_exposed_vulnerability",
            "severity": "critical",
            "issue_category": "security",
        },
    ).model_dump(mode="json")

    tools = _tools_by_name(result)
    assert "write_audit_log" in tools
    audit = tools["write_audit_log"]
    assert audit["category"] == "audit"
    assert audit["status"] == "success"
    assert audit["output"]["event_type"] == "remediation_escalated"
    # Policy compliance is noted both on the connector call and on the result.
    assert audit["input"]["details"]["policy_compliance"] == "compliant"
    assert result["audit_compliance"]["policy_compliance"] == "compliant"
    assert result["audit_compliance"]["approval_type"] == "escalated"

    # The audit entry links back to the originating ticket.
    assert audit["input"]["details"]["ticket_id"] == tools["create_ticket"][
        "output"
    ]["ticket_id"]


def test_escalation_applies_no_fix_and_records_complete_timeline():
    """No workload change is applied; the timeline + report stay complete."""
    result = report_generator.generate_report(
        _escalation_recommendation(),
        _ESC_WORKLOAD,
        {
            "issue_type": "critical_exposed_vulnerability",
            "severity": "critical",
            "issue_category": "security",
        },
    ).model_dump(mode="json")

    # No fix applied -> savings remain projected only.
    assert result["impact_result"]["savings_realised"] is False
    assert result["verification_result"] == "skipped"
    assert result["rollback_triggered"] is False
    # Timeline + traceability links are complete.
    assert result["execution_timeline"]
    assert len(result["execution_timeline"]) == len(result["mcp_tools_executed"])
    assert result["issue_id"] and result["recommendation_id"]
    assert result["workload_id"]
    assert result["user_facing_report"]


# --------------------------------------------------------------------------- #
# auto_fix path: no regression
# --------------------------------------------------------------------------- #
def test_auto_fix_path_still_completes_without_regression():
    """The auto_fix path still works end-to-end and produces a valid result."""
    result = report_generator.generate_report(
        _auto_fix_recommendation(),
        _AUTO_WORKLOAD,
        {"issue_type": "no_monitoring"},
        simulate_healthy=True,
    ).model_dump(mode="json")

    assert result["execution_path"] == "auto_fix"
    assert result["execution_status"] == "completed"
    assert result["verification_result"] == "passed"
    assert result["rollback_triggered"] is False
    assert result["audit_compliance"]["approval_type"] == "auto"
    assert result["audit_compliance"]["policy_compliance"] == "compliant"

    # The runbook's own ticket/notification tools are still recorded uniformly.
    tools = _tools_by_name(result)
    assert "enable_monitoring" in tools
    assert "create_ticket" in tools
    assert all(t["status"] == "success" for t in result["mcp_tools_executed"])


def test_auto_fix_path_does_not_invoke_escalation_notifications():
    """A clean auto-fix must not page owners/security as if it were escalated."""
    result = report_generator.generate_report(
        _auto_fix_recommendation(),
        _AUTO_WORKLOAD,
        {"issue_type": "no_monitoring"},
        simulate_healthy=True,
    ).model_dump(mode="json")

    tools = _tools_by_name(result)
    # The escalation-only notification fan-out should be absent on a clean fix.
    assert "notify_owner" not in tools
    assert "notify_security_team" not in tools
