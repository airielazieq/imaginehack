"""Tests for the approval queue + approvals API (task 5.4).

Covers Requirements 9.1 - 9.4:

- 9.1 the queue is read back sorted by severity (Critical -> High -> Medium ->
  Low);
- 9.2 high-risk items carry a 15-minute escalation countdown;
- 9.3 the countdown auto-escalates the item on timeout (verified by injecting a
  future "now" rather than sleeping);
- 9.4 approve / deny / snooze state transitions behave correctly.

A small API smoke test exercises GET / approve / deny / snooze / 404 / 409
through the FastAPI surface. An isolated temp SQLite DB is configured before the
app is imported so tests never touch the real clover.db.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# --- Configure an isolated temp DB BEFORE importing the app/config -----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_approval_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from backend.modules.self_healing.approval_queue import (  # noqa: E402
    ApprovalQueue,
    InvalidTransition,
    severity_rank,
)
from backend.schemas.recommendation import (  # noqa: E402
    ForecastComponent,
    ForecastModelResult,
    OptimizationImpactForecast,
    Recommendation,
    RuleTriggered,
)

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_recommendation(
    *,
    recommendation_id: str,
    risk_level: str = "high",
    workload_id: str = "wl-test-001",
    issue_id: str | None = None,
    action: str = "resize_workload",
) -> Recommendation:
    """Build a minimal-but-valid Recommendation for queue tests."""
    zero = ForecastComponent(cost_30d=0.0, energy_30d_kwh=0.0, carbon_30d_kgco2e=0.0)
    return Recommendation(
        recommendation_id=recommendation_id,
        issue_id=issue_id or f"iss-{recommendation_id}",
        workload_id=workload_id,
        recommended_action=action,
        action_category="cost_energy_carbon",
        recommendation_type="resize_workload",
        rule_triggered=RuleTriggered(rule_id="RULE-COST-001", conditions_matched=["cpu<10"]),
        forecast_model_result=ForecastModelResult(
            model_name="deterministic_forecast_fallback",
            predicted_cost_30d=100.0,
            predicted_energy_kwh_30d=50.0,
            predicted_carbon_kgco2e_30d=20.0,
        ),
        optimization_impact_forecast=OptimizationImpactForecast(
            forecast_without_action=zero,
            forecast_after_action=zero,
            projected_savings=zero,
        ),
        risk_level=risk_level,
        required_execution_mode="user_approval_required",
        approval_required=True,
        mcp_tools=["resize_resource", "notify_owner"],
        llm_recommendation_explanation="Resize the over-provisioned workload.",
        rollback_note="Restore prior instance size.",
        created_at=T0,
    )


@pytest.fixture
def queue() -> ApprovalQueue:
    """A fresh queue with default (safety_rules) timers."""
    return ApprovalQueue()


# --------------------------------------------------------------------------- #
# Severity ordering (Req 9.1)
# --------------------------------------------------------------------------- #
def test_queue_sorted_critical_to_low(queue):
    severities = ["medium", "critical", "low", "high"]
    for i, sev in enumerate(severities):
        queue.add(
            _make_recommendation(recommendation_id=f"rec-{i}", risk_level="medium"),
            severity=sev,
            now=T0 + timedelta(seconds=i),
        )

    listed = queue.list_items(now=T0)
    ordered = [item.severity for item in listed]
    assert ordered == ["critical", "high", "medium", "low"]
    # Monotonic non-increasing by rank.
    ranks = [severity_rank(s) for s in ordered]
    assert all(ranks[i] >= ranks[i + 1] for i in range(len(ranks) - 1))


def test_same_severity_breaks_ties_oldest_first(queue):
    queue.add(_make_recommendation(recommendation_id="rec-late", risk_level="medium"),
              severity="high", now=T0 + timedelta(minutes=5))
    queue.add(_make_recommendation(recommendation_id="rec-early", risk_level="medium"),
              severity="high", now=T0)
    listed = queue.list_items(now=T0 + timedelta(minutes=6))
    assert [i.approval_id for i in listed] == ["rec-early", "rec-late"]


# --------------------------------------------------------------------------- #
# Escalation countdown (Req 9.2)
# --------------------------------------------------------------------------- #
def test_high_risk_item_gets_15_minute_countdown(queue):
    item = queue.add(_make_recommendation(recommendation_id="rec-hi", risk_level="high"), now=T0)
    assert item.escalation_deadline == T0 + timedelta(minutes=15)
    assert item.seconds_until_escalation(now=T0) == 15 * 60


def test_medium_risk_item_has_no_countdown(queue):
    item = queue.add(_make_recommendation(recommendation_id="rec-md", risk_level="medium"), now=T0)
    assert item.escalation_deadline is None
    assert item.seconds_until_escalation(now=T0) is None


# --------------------------------------------------------------------------- #
# Auto-escalation on timeout (Req 9.3) - inject a future "now"
# --------------------------------------------------------------------------- #
def test_auto_escalates_on_timeout(queue):
    queue.add(_make_recommendation(recommendation_id="rec-hi", risk_level="high"), now=T0)

    # Just before the deadline: still pending.
    before = queue.list_items(now=T0 + timedelta(minutes=14, seconds=59))
    assert before[0].status == "pending"

    # At/after the deadline: auto-escalated.
    after = queue.process_escalations(now=T0 + timedelta(minutes=15))
    assert len(after) == 1
    assert after[0].status == "escalated"
    assert queue.get("rec-hi").status == "escalated"


def test_escalated_item_cannot_be_approved(queue):
    queue.add(_make_recommendation(recommendation_id="rec-hi", risk_level="high"), now=T0)
    queue.process_escalations(now=T0 + timedelta(minutes=16))
    with pytest.raises(InvalidTransition):
        queue.approve("rec-hi", now=T0 + timedelta(minutes=16))


# --------------------------------------------------------------------------- #
# Decision transitions (Req 9.4)
# --------------------------------------------------------------------------- #
def test_approve_transition(queue):
    queue.add(_make_recommendation(recommendation_id="rec-1", risk_level="high"), now=T0)
    item = queue.approve("rec-1", selected_mcp_tools=["resize_resource"], now=T0 + timedelta(minutes=1))
    assert item.status == "approved"
    assert item.resolved_at == T0 + timedelta(minutes=1)
    assert item.selected_mcp_tools == ["resize_resource"]
    # Approved items leave the live queue.
    assert queue.list_items(now=T0 + timedelta(minutes=1)) == []


def test_deny_transition(queue):
    queue.add(_make_recommendation(recommendation_id="rec-2", risk_level="medium"), severity="medium", now=T0)
    item = queue.deny("rec-2", now=T0 + timedelta(minutes=1))
    assert item.status == "denied"
    assert queue.list_items(now=T0 + timedelta(minutes=1)) == []


def test_snooze_pushes_escalation_deadline(queue):
    queue.add(_make_recommendation(recommendation_id="rec-3", risk_level="high"), now=T0)
    item = queue.snooze("rec-3", now=T0 + timedelta(minutes=5))
    assert item.status == "snoozed"
    # Default snooze is 30 minutes from "now".
    assert item.escalation_deadline == T0 + timedelta(minutes=35)
    # Snoozed item is still live and does NOT escalate at the original 15-min mark.
    listed = queue.list_items(now=T0 + timedelta(minutes=16))
    assert listed[0].status == "snoozed"
    # ...but escalates once the new deadline passes.
    queue.process_escalations(now=T0 + timedelta(minutes=36))
    assert queue.get("rec-3").status == "escalated"


def test_double_approve_is_invalid(queue):
    queue.add(_make_recommendation(recommendation_id="rec-4", risk_level="high"), now=T0)
    queue.approve("rec-4", now=T0)
    with pytest.raises(InvalidTransition):
        queue.deny("rec-4", now=T0)


def test_decisions_on_unknown_id_return_none(queue):
    assert queue.approve("nope") is None
    assert queue.deny("nope") is None
    assert queue.snooze("nope") is None


# --------------------------------------------------------------------------- #
# API smoke test
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded_queue():
    """Reset the singleton queue and seed a few items for API tests."""
    from backend.modules.self_healing.approval_queue import approval_queue

    approval_queue.clear()
    # Seed at real "now" so the live API endpoints (which use the real clock)
    # see escalation deadlines in the future rather than already-expired.
    now = datetime.now(timezone.utc)
    approval_queue.add(_make_recommendation(recommendation_id="api-crit", risk_level="high"),
                       severity="critical", now=now)
    approval_queue.add(_make_recommendation(recommendation_id="api-med", risk_level="medium"),
                       severity="medium", now=now)
    yield approval_queue
    approval_queue.clear()


def test_api_list_is_severity_sorted(client, seeded_queue):
    resp = client.get("/api/approvals")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    approvals = body["data"]["approvals"]
    assert body["data"]["count"] == 2
    assert [a["severity"] for a in approvals] == ["critical", "medium"]
    assert approvals[0]["seconds_until_escalation"] is not None  # high risk -> timer


def test_api_approve_and_deny(client, seeded_queue):
    approve = client.post(
        "/api/approvals/api-crit/approve",
        json={"selected_mcp_tools": ["resize_resource"]},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["data"]["status"] == "approved"

    deny = client.post("/api/approvals/api-med/deny")
    assert deny.status_code == 200, deny.text
    assert deny.json()["data"]["status"] == "denied"

    # Both have left the live queue.
    assert client.get("/api/approvals").json()["data"]["count"] == 0


def test_api_snooze(client, seeded_queue):
    resp = client.post("/api/approvals/api-crit/snooze", json={"minutes": 45})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "snoozed"


def test_api_unknown_id_returns_404(client, seeded_queue):
    resp = client.post("/api/approvals/does-not-exist/approve")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_api_double_decision_returns_409(client, seeded_queue):
    client.post("/api/approvals/api-med/approve")
    again = client.post("/api/approvals/api-med/deny")
    assert again.status_code == 409
    assert again.json()["code"] == "CONFLICT"


def teardown_module(module):  # noqa: D401 - pytest hook
    """Remove the temp DB directory created for this module."""
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
