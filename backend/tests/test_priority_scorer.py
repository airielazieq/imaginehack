"""Tests for the Priority Score computation engine (task 7.1).

Covers Requirements 12.1, 12.2, 12.3:

- Valid weights (sum = 1.0) + derived factors -> a score in [0, 100] rounded to
  one decimal place; the configured weights load and validate.
- Invalid weight configurations (not summing to 1.0, missing a factor) are
  rejected with a ``ValueError`` (Requirement 12.2).
- Missing factors have their weight redistributed proportionally across the
  available factors and are reported in ``unavailable_factors``.
- An Issue/Recommendation/Remediation state-change event triggers a
  recomputation (Requirement 12.3).

Pure-function tests use an isolated temp SQLite DB via the ``db_path`` override
so they never touch the real clover.db.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from backend.core.database import init_db
from backend.core.event_bus import Event, EventType, event_bus
from backend.modules.scoring import priority_scorer
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload
from backend.services import telemetry_service, workload_service


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db_path(tmp_path) -> str:
    """An initialized, isolated SQLite DB for a single test."""
    path = str(tmp_path / "scoring_test.db")
    init_db(path)
    return path


def _workload(workload_id: str, *, environment: str, criticality: str) -> Workload:
    return Workload(
        workload_id=workload_id,
        workload_name="Test Workload",
        workload_type="test",
        cloud_service_type="vm",
        environment=environment,  # type: ignore[arg-type]
        region="us-east-1",
        owner_team="platform-team",
        construction_workflow="project_management_dashboard",
        workflow_criticality=criticality,  # type: ignore[arg-type]
        status="healthy",
    )


def _telemetry(workload_id: str, **overrides) -> TelemetrySnapshot:
    base = dict(
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
        monitoring_enabled=True,
        cost_per_hour=0.5,
        cost_24h=12.0,
        cost_30d_forecast=360.0,
        energy_kwh_24h=14.0,
        carbon_kgco2e_24h=5.6,
        carbon_intensity_gco2_per_kwh=400.0,
        timestamp=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return TelemetrySnapshot(**base)


# --------------------------------------------------------------------------- #
# Weight loading + validation (Requirement 12.2)
# --------------------------------------------------------------------------- #
def test_configured_weights_load_and_sum_to_one():
    weights = priority_scorer.load_weights()
    assert set(weights) == set(priority_scorer.FACTOR_NAMES)
    assert abs(sum(weights.values()) - 1.0) <= 1e-6


def test_invalid_weight_sum_is_rejected(monkeypatch):
    bad = {name: 0.1 for name in priority_scorer.FACTOR_NAMES}  # sums to 0.6
    monkeypatch.setattr(
        priority_scorer, "load_policy", lambda _name: {"weights": bad}
    )
    with pytest.raises(ValueError, match="sum to 1.0"):
        priority_scorer.load_weights()


def test_missing_weight_key_is_rejected(monkeypatch):
    partial = {name: 1.0 / 5 for name in priority_scorer.FACTOR_NAMES[:-1]}
    monkeypatch.setattr(
        priority_scorer, "load_policy", lambda _name: {"weights": partial}
    )
    with pytest.raises(ValueError, match="missing weight"):
        priority_scorer.load_weights()


# --------------------------------------------------------------------------- #
# Valid score in [0, 100] with 1 decimal place (Requirement 12.1)
# --------------------------------------------------------------------------- #
def test_score_in_bounds_and_one_decimal_place(db_path):
    wl = _workload("wl-a", environment="production", criticality="high")
    workload_service.upsert_workload(wl, db_path=db_path)
    telemetry_service.persist_snapshot(_telemetry("wl-a"), db_path=db_path)

    score = priority_scorer.compute_for_workload("wl-a", db_path=db_path)

    assert score.workload_id == "wl-a"
    assert 0.0 <= score.score <= 100.0
    # Rounded to a single decimal place.
    assert score.score == round(score.score, 1)


def test_high_security_telemetry_raises_score(db_path):
    workload_service.upsert_workload(
        _workload("wl-sec", environment="production", criticality="critical"),
        db_path=db_path,
    )
    workload_service.upsert_workload(
        _workload("wl-safe", environment="development", criticality="low"),
        db_path=db_path,
    )
    telemetry_service.persist_snapshot(
        _telemetry(
            "wl-sec",
            vulnerability_severity="critical",
            public_exposure=True,
            public_storage=True,
            access_anomaly_detected=True,
        ),
        db_path=db_path,
    )
    telemetry_service.persist_snapshot(_telemetry("wl-safe"), db_path=db_path)

    risky = priority_scorer.compute_for_workload("wl-sec", db_path=db_path)
    safe = priority_scorer.compute_for_workload("wl-safe", db_path=db_path)

    assert risky.security_severity == 1.0
    assert risky.score > safe.score


def test_deterministic_for_fixed_state(db_path):
    workload_service.upsert_workload(
        _workload("wl-d", environment="staging", criticality="medium"), db_path=db_path
    )
    telemetry_service.persist_snapshot(_telemetry("wl-d"), db_path=db_path)
    first = priority_scorer.compute_for_workload("wl-d", db_path=db_path)
    second = priority_scorer.compute_for_workload("wl-d", db_path=db_path)
    assert first.score == second.score
    assert first.model_dump(exclude={"computed_at"}) == second.model_dump(
        exclude={"computed_at"}
    )


# --------------------------------------------------------------------------- #
# Missing-factor weight redistribution (Requirement 12.x / spec A2)
# --------------------------------------------------------------------------- #
def test_missing_factors_are_listed_and_weight_redistributed(db_path):
    # Only a workload exists (no telemetry, no recommendation/remediation):
    # security/energy/cost + self_healing_safety cannot be derived.
    workload_service.upsert_workload(
        _workload("wl-m", environment="production", criticality="critical"),
        db_path=db_path,
    )

    score = priority_scorer.compute_for_workload("wl-m", db_path=db_path)

    assert sorted(score.unavailable_factors) == sorted(
        ["security_severity", "energy_waste", "cost_waste", "self_healing_safety"]
    )
    # Both available factors derive to 1.0 (production + critical); after
    # proportional redistribution the available weights sum to 1.0 -> 100.0.
    assert score.environment_type == 1.0
    assert score.workflow_criticality == 1.0
    assert score.score == 100.0
    # Unavailable factors are stored as 0.0.
    assert score.security_severity == 0.0
    assert score.self_healing_safety == 0.0


def test_all_factors_missing_yields_zero(db_path):
    score = priority_scorer.compute_for_workload("wl-ghost", db_path=db_path)
    assert score.score == 0.0
    assert sorted(score.unavailable_factors) == sorted(priority_scorer.FACTOR_NAMES)


def test_redistribution_matches_manual_calc(db_path):
    # Workload + telemetry available (5 factors); self_healing_safety missing.
    workload_service.upsert_workload(
        _workload("wl-calc", environment="production", criticality="critical"),
        db_path=db_path,
    )
    telemetry_service.persist_snapshot(
        _telemetry(
            "wl-calc",
            cpu_usage_percent=0.0,
            runtime_hours_24h=24.0,
            vulnerability_severity="critical",
            public_exposure=True,
        ),
        db_path=db_path,
    )

    weights = priority_scorer.load_weights()
    score = priority_scorer.compute_for_workload("wl-calc", db_path=db_path)

    assert score.unavailable_factors == ["self_healing_safety"]

    factors = {
        "security_severity": score.security_severity,
        "energy_waste": score.energy_waste,
        "cost_waste": score.cost_waste,
        "workflow_criticality": score.workflow_criticality,
        "environment_type": score.environment_type,
    }
    available_weight_total = sum(weights[name] for name in factors)
    expected01 = sum(
        (weights[name] / available_weight_total) * value
        for name, value in factors.items()
    )
    assert score.score == round(expected01 * 100.0, 1)


# --------------------------------------------------------------------------- #
# Recomputation on state-change events (Requirement 12.3)
# --------------------------------------------------------------------------- #
def test_state_change_event_triggers_recompute(monkeypatch):
    recomputed: list[str] = []

    async def _fake_recompute(workload_id, **_kwargs):
        recomputed.append(workload_id)

    monkeypatch.setattr(priority_scorer, "recompute_and_emit", _fake_recompute)
    priority_scorer.register_subscriptions()

    for event_type in (
        EventType.ISSUE_DETECTED,
        EventType.RECOMMENDATION_GENERATED,
        EventType.REMEDIATION_COMPLETED,
    ):
        recomputed.clear()
        event = Event(event_type=event_type, payload={"workload_id": "wl-evt"})
        asyncio.run(event_bus.publish_and_wait(event))
        assert recomputed == ["wl-evt"], f"{event_type} should trigger recompute"


def test_recompute_and_emit_publishes_score_updated(db_path, monkeypatch):
    workload_service.upsert_workload(
        _workload("wl-emit", environment="production", criticality="high"),
        db_path=db_path,
    )
    telemetry_service.persist_snapshot(_telemetry("wl-emit"), db_path=db_path)

    captured: list[Event] = []

    async def _probe(event: Event) -> None:
        captured.append(event)

    event_bus.subscribe(EventType.SCORE_UPDATED, _probe)
    try:
        async def _run():
            score = await priority_scorer.recompute_and_emit(
                "wl-emit", db_path=db_path
            )
            # SCORE_UPDATED is dispatched fire-and-forget; let the task run.
            for _ in range(3):
                await asyncio.sleep(0)
            return score

        score = asyncio.run(_run())
        assert captured, "SCORE_UPDATED should have been published"
        assert captured[-1].payload["workload_id"] == "wl-emit"
        assert captured[-1].payload["score"] == score.score
        assert 0.0 <= score.score <= 100.0
    finally:
        event_bus.unsubscribe(EventType.SCORE_UPDATED, _probe)
