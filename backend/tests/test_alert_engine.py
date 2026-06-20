"""Tests for the alert engine (task 16.1).

Covers Requirement 13.1 (generation half of the Alert System):

- The score-to-severity mapping (``>80`` critical, ``60-80`` high, ``30-60``
  medium, ``<=30`` low) at its band boundaries.
- ``build_alert`` returns ``None`` when the Priority Score does not exceed the
  generation threshold, and a fully-populated, validated :class:`Alert` when it
  does (severity derived from the score).
- ``generate_for_workload`` persists the alert and publishes an ``ALERT_FIRED``
  event on the bus.
- The ``SCORE_UPDATED`` subscriber generates an alert end-to-end.
- The query helpers (list with workload filter, severity/status filters,
  active-alert lookup) return the expected records.
- Enrichment: ``construction_workflow`` from the workload and
  ``self_healing_eligible`` from the latest auto-fix recommendation.

All tests use an isolated temp SQLite DB via the ``db_path`` override so they
never touch the real clover.db. Regular pytest unit tests (no Hypothesis).
"""

from __future__ import annotations

import asyncio

import pytest

from backend.core.database import init_db
from backend.core.event_bus import Event, EventType, event_bus
from backend.modules.alerts import alert_engine
from backend.schemas.workload import Workload
from backend.services import alert_service, recommendation_service, workload_service


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db_path(tmp_path) -> str:
    """An initialized, isolated SQLite DB for a single test."""
    path = str(tmp_path / "alerts_test.db")
    init_db(path)
    return path


def _seed_workload(db_path: str, workload_id: str = "wl-alert") -> str:
    workload = Workload(
        workload_id=workload_id,
        workload_name="Field App",
        workload_type="web_service",
        cloud_service_type="vm",
        environment="production",  # type: ignore[arg-type]
        region="us-east-1",
        owner_team="platform-team",
        construction_workflow="site_progress_tracking_system",
        workflow_criticality="high",  # type: ignore[arg-type]
        status="warning",
    )
    workload_service.upsert_workload(workload, db_path=db_path)
    return workload_id


def _drain(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Score-to-severity mapping (Requirement 13.1)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "score, expected",
    [
        (100.0, "critical"),
        (80.1, "critical"),
        (80.0, "high"),     # boundary: not > 80
        (60.1, "high"),
        (60.0, "medium"),   # boundary: not > 60
        (30.1, "medium"),
        (30.0, "low"),      # boundary: not > 30
        (0.0, "low"),
    ],
)
def test_severity_from_score_mapping(score, expected):
    assert alert_engine.severity_from_score(score) == expected


# --------------------------------------------------------------------------- #
# build_alert: threshold + content
# --------------------------------------------------------------------------- #
def test_build_alert_below_threshold_returns_none(db_path):
    _seed_workload(db_path)
    # 30.0 is the generation threshold (not exceeded) -> no alert.
    assert alert_engine.build_alert("wl-alert", 30.0, db_path=db_path) is None
    assert alert_engine.build_alert("wl-alert", 12.5, db_path=db_path) is None


def test_build_alert_populates_fields_and_severity(db_path):
    _seed_workload(db_path)
    priority_score = {
        "security_severity": 0.9,
        "energy_waste": 0.2,
        "cost_waste": 0.55,
    }
    alert = alert_engine.build_alert(
        "wl-alert", 85.0, priority_score=priority_score, db_path=db_path
    )
    assert alert is not None
    assert alert.severity == "critical"
    assert alert.workload_id == "wl-alert"
    assert alert.priority_score == 85.0
    assert alert.status == "active"
    assert alert.construction_workflow == "site_progress_tracking_system"
    assert alert.alert_id.startswith("alert-")
    # Impact strings reflect the factor levels.
    assert "critical" in alert.security_impact
    assert "elevated" in alert.cost_impact
    assert "low" in alert.energy_impact
    assert len(alert.title) <= 120


def test_build_alert_handles_missing_workload_and_factors(db_path):
    # No workload seeded; engine must still build a valid alert.
    alert = alert_engine.build_alert("ghost-wl", 65.0, db_path=db_path)
    assert alert is not None
    assert alert.severity == "high"
    assert alert.construction_workflow == "unknown"
    assert "no data available" in alert.security_impact


# --------------------------------------------------------------------------- #
# generate_for_workload: persistence + ALERT_FIRED emission
# --------------------------------------------------------------------------- #
def test_generate_persists_and_emits_alert_fired(db_path):
    _seed_workload(db_path)
    fired: list[Event] = []

    async def _capture(event: Event) -> None:
        fired.append(event)

    async def _run():
        event_bus.subscribe(EventType.ALERT_FIRED, _capture)
        try:
            alert = await alert_engine.generate_for_workload(
                "wl-alert", 90.0, priority_score={}, db_path=db_path
            )
            # Let the fire-and-forget ALERT_FIRED task run.
            await asyncio.sleep(0.05)
            return alert
        finally:
            event_bus.unsubscribe(EventType.ALERT_FIRED, _capture)

    alert = _drain(_run())
    assert alert is not None

    # Persisted and retrievable.
    stored = alert_service.get_alert(alert.alert_id, db_path=db_path)
    assert stored is not None
    assert stored["severity"] == "critical"

    # ALERT_FIRED emitted with the expected payload.
    assert len(fired) == 1
    payload = fired[0].payload
    assert payload["workload_id"] == "wl-alert"
    assert payload["alert_id"] == alert.alert_id
    assert payload["severity"] == "critical"
    assert payload["alert"]["alert_id"] == alert.alert_id


def test_generate_below_threshold_does_nothing(db_path):
    _seed_workload(db_path)

    async def _run():
        return await alert_engine.generate_for_workload(
            "wl-alert", 20.0, db_path=db_path
        )

    assert _drain(_run()) is None
    assert alert_service.list_alerts(workload_id="wl-alert", db_path=db_path) == []


# --------------------------------------------------------------------------- #
# SCORE_UPDATED subscriber wiring (end-to-end)
# --------------------------------------------------------------------------- #
def test_score_updated_event_generates_alert(db_path, monkeypatch):
    _seed_workload(db_path)

    # Route the handler's generation into the isolated DB (the handler itself
    # does not take a db_path, mirroring the audit-service test pattern).
    real_generate = alert_engine.generate_for_workload

    async def _patched(workload_id, score, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return await real_generate(workload_id, score, **kwargs)

    monkeypatch.setattr(alert_engine, "generate_for_workload", _patched)

    async def _run():
        await alert_engine._on_score_updated(
            Event(
                event_type=EventType.SCORE_UPDATED,
                payload={
                    "workload_id": "wl-alert",
                    "score": 75.0,
                    "priority_score": {"security_severity": 0.8},
                },
            )
        )

    _drain(_run())

    alerts = alert_service.list_alerts(workload_id="wl-alert", db_path=db_path)
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "high"


# --------------------------------------------------------------------------- #
# Query helpers + enrichment
# --------------------------------------------------------------------------- #
def test_list_alerts_filters_by_workload_and_severity(db_path):
    _seed_workload(db_path, "wl-a")
    _seed_workload(db_path, "wl-b")

    async def _run():
        await alert_engine.generate_for_workload("wl-a", 90.0, db_path=db_path)
        await alert_engine.generate_for_workload("wl-b", 50.0, db_path=db_path)

    _drain(_run())

    all_alerts = alert_service.list_alerts(db_path=db_path)
    assert len(all_alerts) == 2

    only_a = alert_service.list_alerts(workload_id="wl-a", db_path=db_path)
    assert len(only_a) == 1
    assert only_a[0]["workload_id"] == "wl-a"
    assert only_a[0]["severity"] == "critical"

    crits = alert_service.list_alerts(severity="critical", db_path=db_path)
    assert len(crits) == 1
    assert crits[0]["workload_id"] == "wl-a"

    active = alert_service.get_active_alert("wl-b", db_path=db_path)
    assert active is not None
    assert active["severity"] == "medium"


def test_self_healing_eligible_from_auto_fix_recommendation(db_path, monkeypatch):
    _seed_workload(db_path)

    monkeypatch.setattr(
        recommendation_service,
        "list_recommendations",
        lambda **kwargs: [
            {
                "recommendation_type": "rightsize_instance",
                "required_execution_mode": "auto_fix",
            }
        ],
    )

    alert = alert_engine.build_alert("wl-alert", 70.0, db_path=db_path)
    assert alert is not None
    assert alert.self_healing_eligible is True
    assert alert.recommended_action == "rightsize_instance"


def test_self_healing_not_eligible_when_approval_required(db_path, monkeypatch):
    _seed_workload(db_path)

    monkeypatch.setattr(
        recommendation_service,
        "list_recommendations",
        lambda **kwargs: [
            {
                "recommendation_type": "rotate_credentials",
                "required_execution_mode": "user_approval_required",
            }
        ],
    )

    alert = alert_engine.build_alert("wl-alert", 70.0, db_path=db_path)
    assert alert is not None
    assert alert.self_healing_eligible is False
