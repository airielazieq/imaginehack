"""Tests for the remediation report generator + Remediation API (task 5.5).

Covers Requirements 8.4, 11.1, 11.2, 11.3 (design Property 9 — Remediation
Report Completeness):

- The report generator assembles a complete RemediationResult for every
  execution path (auto-fix, approved, escalation) with a non-empty
  execution_timeline, mcp_tools_executed list, safety_decision, audit_compliance
  record, user_facing_report narrative, and valid traceability links.
- End to end through the API: trigger a mock scenario -> detection ->
  recommendation -> POST evaluate (safety path) -> POST execute (auto-fix on a
  non-prod workload) -> GET report returns the full RemediationResult; the row
  is persisted with traceability links and REMEDIATION_COMPLETED is emitted.
- An escalation path (critical production vulnerability) produces a
  human_escalation report with ticket + notification connector invocations.

An isolated temp SQLite DB is configured via CLOVER_DB_PATH before the app is
imported so tests never touch the real clover.db.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_remediation_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # ensure the temp DB path is picked up

from fastapi.testclient import TestClient  # noqa: E402

from backend.core.event_bus import EventType, event_bus  # noqa: E402
from backend.main import app  # noqa: E402
from backend.modules.self_healing import report_generator  # noqa: E402
from backend.services import recommendation_service  # noqa: E402


# --------------------------------------------------------------------------- #
# Crafted recommendation fixtures (unit-level, no DB / pipeline needed)
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


def _auto_fix_recommendation() -> dict:
    """A non-prod, reversible, non-security recommendation -> auto_fix."""
    return {
        "recommendation_id": "rec-auto-001",
        "issue_id": "iss-auto-001",
        "workload_id": "wl-ci-pipeline-001",
        "recommended_action": "Enable monitoring on the workload.",
        "action_category": "monitoring",
        "recommendation_type": "enable_monitoring",
        "risk_level": "low",
        "required_execution_mode": "auto_fix",
        "mcp_tools": ["enable_monitoring", "create_ticket"],
        "rollback_note": "Disable the newly enabled monitoring configuration.",
        "optimization_impact_forecast": _impact_forecast(),
    }


def _escalation_recommendation() -> dict:
    """A critical production security recommendation -> human_escalation."""
    return {
        "recommendation_id": "rec-esc-001",
        "issue_id": "iss-esc-001",
        "workload_id": "wl-field-app-001",
        "recommended_action": "Restrict public access and patch the workload.",
        "action_category": "security",
        "recommendation_type": "restrict_access",
        "risk_level": "critical",
        "required_execution_mode": "human_escalation_required",
        "mcp_tools": [
            "restrict_public_access",
            "pull_container_image",
            "notify_security_team",
        ],
        "rollback_note": "Re-open access and restore the previous network policy.",
        "optimization_impact_forecast": _impact_forecast(),
    }


_AUTO_WORKLOAD = {
    "workload_id": "wl-ci-pipeline-001",
    "workload_name": "CI/CD Pipeline",
    "environment": "development",
    "workflow_criticality": "medium",
    "owner_team": "devops-team",
}
_ESC_WORKLOAD = {
    "workload_id": "wl-field-app-001",
    "workload_name": "Field App",
    "environment": "production",
    "workflow_criticality": "high",
    "owner_team": "field-ops-team",
}


def _assert_complete_result(result: dict, *, expected_path: str) -> None:
    """Assert Property 9: a remediation report is complete and traceable."""
    assert result["execution_path"] == expected_path
    # Traceability links (Requirement 11.3) must all be non-empty.
    assert result["issue_id"]
    assert result["recommendation_id"]
    assert result["workload_id"]
    # Core report content (Requirements 11.1, 11.2).
    assert result["execution_timeline"], "execution_timeline must be non-empty"
    assert result["mcp_tools_executed"], "mcp_tools_executed must be non-empty"
    assert result["safety_decision"]["why_safe"]
    assert isinstance(result["safety_decision"]["approval_required"], bool)
    assert result["audit_compliance"]["approval_type"]
    assert result["audit_compliance"]["policy_compliance"] == "compliant"
    assert result["audit_compliance"]["retention_expires"]
    assert isinstance(result["user_facing_report"], str)
    assert len(result["user_facing_report"]) > 0
    assert result["ai_decision_steps"], "ai_decision_steps must be non-empty"
    for step in result["ai_decision_steps"]:
        assert step["timestamp"]
    # impact_result before/after/savings present.
    assert "before" in result["impact_result"]
    assert "after" in result["impact_result"]
    assert "simulated_savings" in result["impact_result"]


# --------------------------------------------------------------------------- #
# Unit-level: report generator (deterministic, no DB)
# --------------------------------------------------------------------------- #
def test_evaluate_routes_auto_fix_for_non_prod_monitoring():
    decision = report_generator.evaluate(_auto_fix_recommendation(), _AUTO_WORKLOAD)
    assert decision.execution_path == "auto_fix"
    assert decision.approval_required is False
    assert decision.rollback_available is True


def test_evaluate_routes_escalation_for_critical_prod_security():
    decision = report_generator.evaluate(
        _escalation_recommendation(),
        _ESC_WORKLOAD,
        {"issue_type": "critical_exposed_vulnerability", "severity": "critical"},
    )
    assert decision.execution_path == "human_escalation_required"
    assert decision.approval_required is True


def test_generate_report_auto_fix_completed():
    result = report_generator.generate_report(
        _auto_fix_recommendation(),
        _AUTO_WORKLOAD,
        {"issue_type": "no_monitoring"},
        simulate_healthy=True,
    ).model_dump(mode="json")

    _assert_complete_result(result, expected_path="auto_fix")
    assert result["execution_status"] == "completed"
    assert result["verification_result"] == "passed"
    assert result["rollback_triggered"] is False
    assert result["audit_compliance"]["approval_type"] == "auto"
    # Every recommended MCP tool ran.
    tools = {t["tool"] for t in result["mcp_tools_executed"]}
    assert {"enable_monitoring", "create_ticket"}.issubset(tools)


def test_generate_report_auto_fix_failure_rolls_back_and_escalates():
    # Force verification to fail -> rollback + escalate (Requirement 8.3).
    result = report_generator.generate_report(
        _auto_fix_recommendation(),
        _AUTO_WORKLOAD,
        {"issue_type": "no_monitoring"},
        simulate_healthy=False,
    ).model_dump(mode="json")

    _assert_complete_result(result, expected_path="auto_fix")
    assert result["execution_status"] == "escalated"
    assert result["verification_result"] == "failed"
    assert result["rollback_triggered"] is True


def test_generate_report_escalation_invokes_ticket_and_notifications():
    result = report_generator.generate_report(
        _escalation_recommendation(),
        _ESC_WORKLOAD,
        {"issue_type": "critical_exposed_vulnerability", "severity": "critical",
         "issue_category": "security"},
    ).model_dump(mode="json")

    _assert_complete_result(result, expected_path="human_escalation")
    assert result["execution_status"] == "escalated"
    assert result["audit_compliance"]["approval_type"] == "escalated"

    tools = {t["tool"] for t in result["mcp_tools_executed"]}
    # Requirement 10.1 (ticket) + 10.2 (owner + security notifications).
    assert "create_ticket" in tools
    assert "notify_owner" in tools
    assert "notify_security_team" in tools
    # No fix was applied -> savings remain projected only.
    assert result["impact_result"]["savings_realised"] is False


def test_retention_expires_in_the_future():
    result = report_generator.generate_report(
        _auto_fix_recommendation(), _AUTO_WORKLOAD, simulate_healthy=True
    )
    assert result.audit_compliance.retention_expires > datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# API integration
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def client():
    """TestClient with lifespan active (seeds workloads + baseline + subscribes)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_between_tests(client):
    # The approval queue is an in-memory singleton that survives /api/mock/reset,
    # so clear it explicitly to isolate tests that exercise the approval gate.
    from backend.modules.self_healing.approval_queue import approval_queue

    client.post("/api/mock/reset")
    approval_queue.clear()
    yield


def _wait_for_recommendation(client, workload_id: str, *, attempts: int = 30):
    """Poll for a recommendation produced by the ISSUE_DETECTED -> NBA chain."""
    for _ in range(attempts):
        recs = recommendation_service.list_recommendations(workload_id=workload_id)
        if recs:
            return recs[0]
        client.get("/api/mock/status")
    return None


def test_evaluate_endpoint_unknown_recommendation_404(client):
    resp = client.post("/api/remediation/evaluate/rec-does-not-exist")
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"


def test_execute_endpoint_unknown_recommendation_404(client):
    resp = client.post("/api/remediation/execute/rec-does-not-exist")
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"


def test_report_endpoint_unknown_remediation_404(client):
    resp = client.get("/api/remediation/rem-does-not-exist/report")
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"


def test_auto_fix_end_to_end(client):
    """trigger -> detect -> recommend -> evaluate -> execute -> report (auto-fix)."""
    # Subscribe a probe to confirm REMEDIATION_COMPLETED is emitted.
    received: list = []

    async def _probe(event):
        received.append(event)

    event_bus.subscribe(EventType.REMEDIATION_COMPLETED, _probe)
    try:
        trig = client.post("/api/mock/trigger/trigger_missing_monitoring")
        assert trig.status_code == 200, trig.text
        workload_id = trig.json()["data"]["workload_id"]

        recommendation = _wait_for_recommendation(client, workload_id)
        assert recommendation is not None
        rec_id = recommendation["recommendation_id"]

        # Evaluate: should choose the auto-fix path without executing.
        ev = client.post(f"/api/remediation/evaluate/{rec_id}")
        assert ev.status_code == 200, ev.text
        ev_data = ev.json()["data"]
        assert ev_data["execution_path"] == "auto_fix"
        assert ev_data["approval_required"] is False
        # Evaluate must not have persisted a remediation.
        assert recommendation_service.list_recommendations(workload_id=workload_id)

        # Execute: produce + persist the RemediationResult.
        ex = client.post(f"/api/remediation/execute/{rec_id}")
        assert ex.status_code == 200, ex.text
        result = ex.json()["data"]
        _assert_complete_result(result, expected_path="auto_fix")
        assert result["execution_status"] == "completed"
        assert result["recommendation_id"] == rec_id
        assert result["workload_id"] == workload_id

        # GET report returns the persisted, complete result.
        rem_id = result["remediation_id"]
        rep = client.get(f"/api/remediation/{rem_id}/report")
        assert rep.status_code == 200, rep.text
        stored = rep.json()["data"]
        _assert_complete_result(stored, expected_path="auto_fix")
        assert stored["remediation_id"] == rem_id

        # The row is persisted with traceability links.
        from backend.core.database import connection

        with connection() as conn:
            row = conn.execute(
                "SELECT recommendation_id, issue_id, workload_id, execution_status "
                "FROM remediations WHERE remediation_id = ?",
                (rem_id,),
            ).fetchone()
        assert row is not None
        assert row["recommendation_id"] == rec_id
        assert row["issue_id"] == result["issue_id"]
        assert row["workload_id"] == workload_id
        assert row["execution_status"] == "completed"

        # The originating issue advanced into the remediation lifecycle:
        # generating the auto-fix recommendation -> recommended; executing it
        # -> auto_fixed (drives the workload Self-Healing tab).
        from backend.services import issue_service

        issue = issue_service.get_issue(result["issue_id"])
        assert issue is not None and issue["status"] == "auto_fixed"

        # REMEDIATION_COMPLETED was emitted (drain the fire-and-forget task).
        for _ in range(10):
            if received:
                break
            client.get("/api/mock/status")
        assert received, "REMEDIATION_COMPLETED event should have been emitted"
        assert received[0].payload["remediation_id"] == rem_id
    finally:
        event_bus.unsubscribe(EventType.REMEDIATION_COMPLETED, _probe)


def test_user_approval_gate_enqueue_block_and_release(client):
    """A user_approval_required remediation must be approved before it can run.

    Drives the full chain (trigger -> detect -> recommend) for a carbon-heavy
    workload, which the safety router classifies as ``user_approval_required``,
    and exercises every state of the guardrail fix:

    - generating the recommendation auto-enqueues it for approval (pending);
    - ``execute`` is refused with HTTP 409 while the item is pending;
    - once approved, ``execute`` runs the approved path and completes;
    - a freshly re-queued + denied copy can never be executed (HTTP 409).
    """
    from backend.modules.self_healing.approval_queue import approval_queue
    from backend.schemas.recommendation import Recommendation
    from backend.services import issue_service

    trig = client.post("/api/mock/trigger/trigger_carbon_heavy_batch_job")
    assert trig.status_code == 200, trig.text
    workload_id = trig.json()["data"]["workload_id"]

    recommendation = _wait_for_recommendation(client, workload_id)
    assert recommendation is not None
    rec_id = recommendation["recommendation_id"]
    issue_id = recommendation["issue_id"]

    # Evaluate confirms the safety path needs human sign-off.
    ev = client.post(f"/api/remediation/evaluate/{rec_id}")
    assert ev.status_code == 200, ev.text
    assert ev.json()["data"]["execution_path"] == "user_approval_required"

    # Generation auto-enqueued the recommendation, still pending, and moved the
    # issue into pending_approval.
    item = approval_queue.get(rec_id)
    assert item is not None, "recommendation should be queued for approval"
    assert item.status == "pending"
    assert issue_service.get_issue(issue_id)["status"] == "pending_approval"

    # Execute is refused while approval is still pending.
    pending = client.post(f"/api/remediation/execute/{rec_id}")
    assert pending.status_code == 409, pending.text

    # Approve -> issue becomes approved; execute is now allowed and runs the
    # approved path, leaving the issue remediated.
    ok = client.post(f"/api/approvals/{rec_id}/approve")
    assert ok.status_code == 200, ok.text
    assert issue_service.get_issue(issue_id)["status"] == "approved"
    ex = client.post(f"/api/remediation/execute/{rec_id}")
    assert ex.status_code == 200, ex.text
    result = ex.json()["data"]
    assert result["execution_path"] == "user_approved"
    assert result["recommendation_id"] == rec_id
    assert issue_service.get_issue(issue_id)["status"] == "remediated"

    # A denied item can never be executed: re-queue a fresh copy and deny it.
    model = Recommendation(**recommendation_service.get_recommendation(rec_id))
    approval_queue.clear()
    approval_queue.add(model)
    deny = client.post(f"/api/approvals/{rec_id}/deny")
    assert deny.status_code == 200, deny.text
    blocked = client.post(f"/api/remediation/execute/{rec_id}")
    assert blocked.status_code == 409, blocked.text


def test_generate_is_idempotent_no_duplicate_approvals(client):
    """Repeated generate calls (revisiting the issue) must not duplicate.

    The IssueDetail page calls POST /recommendations/generate every time it loads
    and on each "Review in approval queue" click. This must return the same
    recommendation and leave a single approval-queue entry — not a new one each
    time.
    """
    from backend.modules.self_healing.approval_queue import approval_queue

    trig = client.post("/api/mock/trigger/trigger_carbon_heavy_batch_job")
    assert trig.status_code == 200, trig.text
    workload_id = trig.json()["data"]["workload_id"]

    rec = _wait_for_recommendation(client, workload_id)
    assert rec is not None
    issue_id = rec["issue_id"]
    original_id = rec["recommendation_id"]

    # Simulate clicking "Review in approval queue" several times.
    for _ in range(4):
        r = client.post(f"/api/recommendations/generate/{issue_id}")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["recommendation_id"] == original_id

    # The dedup invariant, scoped to THIS issue so leftover state from other
    # tests can't perturb the counts: exactly one recommendation exists for the
    # issue (the bug created a fresh one per click), and at most one queue entry
    # references it. Without the fix, the four clicks would balloon both.
    recs = recommendation_service.list_recommendations(issue_id=issue_id)
    assert len(recs) == 1, f"expected 1 recommendation for issue, got {len(recs)}"
    items = [i for i in approval_queue.list_items() if i.issue_id == issue_id]
    assert len(items) <= 1, f"expected <=1 queue item for issue, got {len(items)}"


def test_escalation_end_to_end(client):
    """A critical production vulnerability escalates with ticket + notifications."""
    trig = client.post("/api/mock/trigger/trigger_critical_production_vulnerability")
    assert trig.status_code == 200, trig.text
    workload_id = trig.json()["data"]["workload_id"]

    recommendation = _wait_for_recommendation(client, workload_id)
    assert recommendation is not None
    rec_id = recommendation["recommendation_id"]

    ev = client.post(f"/api/remediation/evaluate/{rec_id}")
    assert ev.status_code == 200, ev.text
    assert ev.json()["data"]["execution_path"] == "human_escalation_required"

    ex = client.post(f"/api/remediation/execute/{rec_id}")
    assert ex.status_code == 200, ex.text
    result = ex.json()["data"]
    _assert_complete_result(result, expected_path="human_escalation")
    assert result["execution_status"] == "escalated"

    tools = {t["tool"] for t in result["mcp_tools_executed"]}
    assert "create_ticket" in tools
    assert "notify_owner" in tools

    # Report is retrievable.
    rep = client.get(f"/api/remediation/{result['remediation_id']}/report")
    assert rep.status_code == 200, rep.text
    assert rep.json()["data"]["execution_path"] == "human_escalation"

    # The originating issue is now marked escalated (drives the Self-Healing tab).
    from backend.services import issue_service

    assert issue_service.get_issue(result["issue_id"])["status"] == "escalated"


def teardown_module(module):  # noqa: D401 - pytest hook
    """Remove the temp DB directory created for this module."""
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
