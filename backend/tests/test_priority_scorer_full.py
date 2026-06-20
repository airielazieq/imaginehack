"""Tests for the full 6-factor weighted Priority Score engine (task 20.1).

Covers the P2 enhancements layered on top of task 7.1 (Requirements 12.1,
12.2, 12.3):

- The weighted combination of **all six** factors equals the normalized
  weighted sum (``score = 100 * Sigma weight_i * factor_i``).
- Weight normalization: the configured weights sum to exactly 1.0 and the
  resulting score is always in ``[0, 100]`` with one decimal place.
- The elevated-factor **constraint** is enforced: ``security_severity`` and
  ``environment_type`` must each be ``>= 1.5x`` the average of the other four
  factor weights, otherwise the configuration is rejected.
- Score ordering: a strictly worse workload scores strictly higher.
- Tiebreaker: when two Priority Scores are equal, the one with the earlier
  ``detection_timestamp`` ranks higher.

These tests use only regular pytest assertions (no Hypothesis). DB-backed
cases use an isolated temp SQLite DB via the ``db_path`` override.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.core.database import init_db
from backend.modules.scoring import priority_scorer
from backend.schemas.scoring import PriorityScore
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload
from backend.services import telemetry_service, workload_service


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db_path(tmp_path) -> str:
    """An initialized, isolated SQLite DB for a single test."""
    path = str(tmp_path / "scoring_full_test.db")
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


def _score(workload_id: str, score: float, detection_timestamp: datetime) -> PriorityScore:
    """Build a minimal PriorityScore for ranking/tiebreaker tests."""
    return PriorityScore(
        workload_id=workload_id,
        score=score,
        security_severity=0.0,
        energy_waste=0.0,
        cost_waste=0.0,
        workflow_criticality=0.0,
        environment_type=0.0,
        self_healing_safety=0.0,
        unavailable_factors=[],
        detection_timestamp=detection_timestamp,
        computed_at=datetime.now(timezone.utc),
    )


# --------------------------------------------------------------------------- #
# Weighted combination of ALL six factors
# --------------------------------------------------------------------------- #
def test_all_six_factors_combine_as_weighted_sum():
    """score = 100 * Sigma(weight_i * factor_i) when every factor is present."""
    weights = priority_scorer.load_weights()
    factors = {
        "security_severity": 0.8,
        "energy_waste": 0.4,
        "cost_waste": 0.6,
        "workflow_criticality": 0.75,
        "environment_type": 1.0,
        "self_healing_safety": 0.6,
    }

    score, unavailable = priority_scorer._aggregate(factors, weights)

    expected = round(sum(weights[name] * value for name, value in factors.items()) * 100.0, 1)
    assert unavailable == []
    assert score == expected
    assert 0.0 <= score <= 100.0


def test_all_factors_at_max_gives_100_and_all_zero_gives_0():
    weights = priority_scorer.load_weights()
    all_max = {name: 1.0 for name in priority_scorer.FACTOR_NAMES}
    all_zero = {name: 0.0 for name in priority_scorer.FACTOR_NAMES}

    top, _ = priority_scorer._aggregate(all_max, weights)
    bottom, _ = priority_scorer._aggregate(all_zero, weights)

    assert top == 100.0
    assert bottom == 0.0


# --------------------------------------------------------------------------- #
# Weight normalization (weights sum to 1.0; score in [0, 100], 1 dp)
# --------------------------------------------------------------------------- #
def test_configured_weights_sum_to_one():
    weights = priority_scorer.load_weights()
    assert set(weights) == set(priority_scorer.FACTOR_NAMES)
    assert abs(sum(weights.values()) - 1.0) <= 1e-6


def test_computed_score_is_in_bounds_with_one_decimal(db_path):
    workload_service.upsert_workload(
        _workload("wl-norm", environment="production", criticality="high"),
        db_path=db_path,
    )
    telemetry_service.persist_snapshot(
        _telemetry("wl-norm", vulnerability_severity="high", public_exposure=True),
        db_path=db_path,
    )
    score = priority_scorer.compute_for_workload("wl-norm", db_path=db_path)
    assert 0.0 <= score.score <= 100.0
    assert score.score == round(score.score, 1)


# --------------------------------------------------------------------------- #
# Elevated-factor constraint enforcement (task 20.1 / spec 07 §A1)
# --------------------------------------------------------------------------- #
def test_configured_weights_satisfy_elevated_constraint():
    """The shipped config must load without raising (constraint satisfied)."""
    weights = priority_scorer.load_weights()
    elevated = ("security_severity", "environment_type")
    others = [w for name, w in weights.items() if name not in elevated]
    others_avg = sum(others) / len(others)
    for name in elevated:
        assert weights[name] + 1e-6 >= 1.5 * others_avg


def test_elevated_constraint_violation_is_rejected(monkeypatch):
    # Uniform weights sum to 1.0 but the elevated factors equal the average of
    # the others (1/6), failing the >= 1.5x requirement.
    uniform = {name: 1.0 / 6.0 for name in priority_scorer.FACTOR_NAMES}
    monkeypatch.setattr(
        priority_scorer, "load_policy", lambda _name: {"weights": uniform}
    )
    with pytest.raises(ValueError, match="elevated-factor constraint"):
        priority_scorer.load_weights()


def test_weight_sum_checked_before_elevated_constraint(monkeypatch):
    # Sum != 1.0 must surface the sum error first, not the elevated one.
    bad = {name: 0.1 for name in priority_scorer.FACTOR_NAMES}  # sums to 0.6
    monkeypatch.setattr(
        priority_scorer, "load_policy", lambda _name: {"weights": bad}
    )
    with pytest.raises(ValueError, match="sum to 1.0"):
        priority_scorer.load_weights()


# --------------------------------------------------------------------------- #
# Score ordering: a strictly worse workload scores strictly higher
# --------------------------------------------------------------------------- #
def test_strictly_worse_workload_scores_higher(db_path):
    # Worse: production + critical workflow + critical vuln + public + idle.
    workload_service.upsert_workload(
        _workload("wl-worse", environment="production", criticality="critical"),
        db_path=db_path,
    )
    telemetry_service.persist_snapshot(
        _telemetry(
            "wl-worse",
            cpu_usage_percent=1.0,
            runtime_hours_24h=24.0,
            vulnerability_severity="critical",
            critical_vulnerability_count=3,
            public_exposure=True,
            public_storage=True,
            access_anomaly_detected=True,
            cost_24h=200.0,
            cost_30d_forecast=12000.0,
        ),
        db_path=db_path,
    )
    # Better: development + low workflow + healthy/utilized + no exposure.
    workload_service.upsert_workload(
        _workload("wl-better", environment="development", criticality="low"),
        db_path=db_path,
    )
    telemetry_service.persist_snapshot(
        _telemetry(
            "wl-better",
            cpu_usage_percent=55.0,
            runtime_hours_24h=6.0,
            vulnerability_severity="none",
        ),
        db_path=db_path,
    )

    worse = priority_scorer.compute_for_workload("wl-worse", db_path=db_path)
    better = priority_scorer.compute_for_workload("wl-better", db_path=db_path)

    assert worse.score > better.score


# --------------------------------------------------------------------------- #
# Tiebreaker: earlier detection_timestamp ranks higher
# --------------------------------------------------------------------------- #
def test_tiebreaker_earlier_detection_ranks_higher():
    now = datetime.now(timezone.utc)
    earlier = _score("wl-old", 75.0, now - timedelta(hours=2))
    later = _score("wl-new", 75.0, now)

    ranked = priority_scorer.rank_scores([later, earlier])

    assert [s.workload_id for s in ranked] == ["wl-old", "wl-new"]


def test_rank_orders_by_score_then_timestamp():
    now = datetime.now(timezone.utc)
    high = _score("wl-high", 90.0, now)
    tie_early = _score("wl-tie-early", 60.0, now - timedelta(minutes=30))
    tie_late = _score("wl-tie-late", 60.0, now)
    low = _score("wl-low", 10.0, now - timedelta(days=1))

    ranked = priority_scorer.rank_scores([tie_late, low, high, tie_early])

    assert [s.workload_id for s in ranked] == [
        "wl-high",
        "wl-tie-early",
        "wl-tie-late",
        "wl-low",
    ]
