"""Tests for the Optimization Impact Calculator (task 4.3).

Covers the two correctness guarantees of
``backend/modules/next_best_action/optimization_impact.py`` (Requirement 6.4):

  * **Arithmetic consistency** - for every dimension,
    ``forecast_without_action - forecast_after_action == projected_savings``.
  * **Non-negativity** - every ``projected_savings`` value is ``>= 0`` and the
    after-action forecast never exceeds the baseline.

Both example-based unit tests and a Hypothesis property check are included,
exercised across all defined recommendation types and a range of baseline
forecast inputs.

**Validates: Requirements 6.2, 6.4**
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.core.config import load_policy
from backend.modules.next_best_action.optimization_impact import (
    DIMENSIONS,
    compute_optimization_impact,
    get_optimization_factors,
)
from backend.schemas.recommendation import OptimizationImpactForecast

# Tolerance for floating-point arithmetic consistency checks.
_TOL = 1e-9

# All recommendation types that carry optimization factors.
_RECOMMENDATION_TYPES = sorted(
    load_policy("recommendation_rules")["optimization_factors_reference"].keys()
)

# The factor-by-factor ("zero savings") types: factor == 1.0 on every dimension.
_NO_SAVINGS_TYPES = {
    "enable_monitoring",
    "restrict_access",
    "investigate_incident",
}


def _dimension_triples(forecast: OptimizationImpactForecast):
    """Yield ``(without, after, savings)`` for each of cost/energy/carbon."""
    w = forecast.forecast_without_action
    a = forecast.forecast_after_action
    s = forecast.projected_savings
    return [
        (w.cost_30d, a.cost_30d, s.cost_30d),
        (w.energy_30d_kwh, a.energy_30d_kwh, s.energy_30d_kwh),
        (w.carbon_30d_kgco2e, a.carbon_30d_kgco2e, s.carbon_30d_kgco2e),
    ]


def _assert_consistent_and_non_negative(forecast: OptimizationImpactForecast):
    for without, after, savings in _dimension_triples(forecast):
        # Arithmetic consistency: without - after == savings.
        assert math.isclose(without - after, savings, abs_tol=_TOL)
        # Non-negativity of savings, and after never exceeds baseline.
        assert savings >= -_TOL
        assert after <= without + _TOL
        assert after >= -_TOL


# --------------------------------------------------------------------------- #
# Example-based unit tests
# --------------------------------------------------------------------------- #
def test_shutdown_and_resize_midpoint_savings():
    """shutdown_and_resize factor range [0.25, 0.50] -> midpoint 0.375 retained."""
    forecast = compute_optimization_impact(
        cost_30d=1000.0,
        energy_kwh_30d=2000.0,
        carbon_kgco2e_30d=800.0,
        recommendation_type="shutdown_and_resize",
    )
    # Midpoint factor 0.375 retained => 62.5% saved.
    assert math.isclose(forecast.forecast_after_action.cost_30d, 375.0, abs_tol=_TOL)
    assert math.isclose(forecast.projected_savings.cost_30d, 625.0, abs_tol=_TOL)
    _assert_consistent_and_non_negative(forecast)


def test_security_type_has_zero_savings():
    """restrict_access factor is 1.0 on every dimension => zero savings."""
    forecast = compute_optimization_impact(
        cost_30d=500.0,
        energy_kwh_30d=300.0,
        carbon_kgco2e_30d=120.0,
        recommendation_type="restrict_access",
    )
    for without, after, savings in _dimension_triples(forecast):
        assert math.isclose(savings, 0.0, abs_tol=_TOL)
        assert math.isclose(after, without, abs_tol=_TOL)
    _assert_consistent_and_non_negative(forecast)


def test_zero_baseline_yields_zero_savings():
    """A zero baseline forecast produces zero after/savings on every dimension."""
    forecast = compute_optimization_impact(
        cost_30d=0.0,
        energy_kwh_30d=0.0,
        carbon_kgco2e_30d=0.0,
        recommendation_type="shutdown_schedule",
    )
    for without, after, savings in _dimension_triples(forecast):
        assert without == 0.0
        assert math.isclose(after, 0.0, abs_tol=_TOL)
        assert math.isclose(savings, 0.0, abs_tol=_TOL)


def test_range_point_min_saves_more_than_max():
    """Lower retained factor (range min) yields larger savings than range max."""
    kwargs = dict(
        cost_30d=1000.0,
        energy_kwh_30d=1000.0,
        carbon_kgco2e_30d=1000.0,
        recommendation_type="resize_workload",  # [0.40, 0.75]
    )
    at_min = compute_optimization_impact(range_point="min", **kwargs)
    at_max = compute_optimization_impact(range_point="max", **kwargs)
    # Retaining the minimum fraction (0.40) saves more than the maximum (0.75).
    assert at_min.projected_savings.cost_30d > at_max.projected_savings.cost_30d
    _assert_consistent_and_non_negative(at_min)
    _assert_consistent_and_non_negative(at_max)


def test_explicit_factors_override_and_clamp():
    """Explicit factors are used; a factor > 1 is clamped to 1.0 (no savings)."""
    forecast = compute_optimization_impact(
        cost_30d=100.0,
        energy_kwh_30d=100.0,
        carbon_kgco2e_30d=100.0,
        optimization_factors={"cost": 1.5, "energy": [0.0, 0.0], "carbon": 0.5},
    )
    # cost factor clamped to 1.0 -> zero savings (never negative).
    assert math.isclose(forecast.projected_savings.cost_30d, 0.0, abs_tol=_TOL)
    # energy factor 0.0 -> full savings.
    assert math.isclose(forecast.projected_savings.energy_30d_kwh, 100.0, abs_tol=_TOL)
    # carbon factor 0.5 -> half savings.
    assert math.isclose(forecast.projected_savings.carbon_30d_kgco2e, 50.0, abs_tol=_TOL)
    _assert_consistent_and_non_negative(forecast)


def test_missing_factor_source_raises():
    with pytest.raises(ValueError):
        compute_optimization_impact(
            cost_30d=10.0, energy_kwh_30d=10.0, carbon_kgco2e_30d=10.0
        )


def test_unknown_recommendation_type_raises():
    with pytest.raises(KeyError):
        get_optimization_factors("does_not_exist")


def test_negative_baseline_raises():
    with pytest.raises(ValueError):
        compute_optimization_impact(
            cost_30d=-1.0,
            energy_kwh_30d=10.0,
            carbon_kgco2e_30d=10.0,
            recommendation_type="resize_workload",
        )


# --------------------------------------------------------------------------- #
# Property-based check: consistency + non-negativity across all types & inputs
# --------------------------------------------------------------------------- #
_non_negative_forecast = st.floats(
    min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
)


@settings(max_examples=200, deadline=None)
@given(
    recommendation_type=st.sampled_from(_RECOMMENDATION_TYPES),
    cost_30d=_non_negative_forecast,
    energy_kwh_30d=_non_negative_forecast,
    carbon_kgco2e_30d=_non_negative_forecast,
    range_point=st.sampled_from(["min", "mid", "max"]),
)
def test_property_consistency_and_non_negativity(
    recommendation_type, cost_30d, energy_kwh_30d, carbon_kgco2e_30d, range_point
):
    """For any type and non-negative baseline: consistent, non-negative savings."""
    forecast = compute_optimization_impact(
        cost_30d=cost_30d,
        energy_kwh_30d=energy_kwh_30d,
        carbon_kgco2e_30d=carbon_kgco2e_30d,
        recommendation_type=recommendation_type,
        range_point=range_point,
    )
    _assert_consistent_and_non_negative(forecast)

    # No-savings recommendation types must leave the forecast unchanged.
    if recommendation_type in _NO_SAVINGS_TYPES:
        for without, after, savings in _dimension_triples(forecast):
            assert math.isclose(savings, 0.0, abs_tol=_TOL)
            assert math.isclose(after, without, abs_tol=_TOL)
