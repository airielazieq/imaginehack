"""Optimization Impact Calculator (Module 2, task 4.3).

Given a baseline 30-day forecast (the cost / energy / carbon the workload is
projected to consume *without* any action) and a recommendation type, this
module computes the :class:`OptimizationImpactForecast` rendered on the
Optimization Impact Forecast card: the before / after / savings projection for
each of the three dimensions.

Semantics (from SDD 05, section 7 "Optimization Impact Forecast"):

    forecast_after_action = forecast_without_action x optimization_factor
    projected_savings     = forecast_without_action - forecast_after_action

The optimization factor is therefore the **retained fraction** of the baseline
forecast that remains after the action is taken (e.g. a factor of ``0.30`` means
the action reduces the dimension to 30% of its no-action value, saving 70%).
Factors live in ``rules/recommendation_rules.json`` keyed by recommendation type
under ``optimization_factors_reference`` (and mirrored on each rule). Each factor
is expressed as a ``[low, high]`` range; this calculator collapses the range to a
single deterministic point (the midpoint by default) so the forecast is
reproducible.

Guarantees enforced for every dimension (Requirement 6.4):
  * arithmetic consistency - ``without - after == savings``
  * non-negativity - ``savings >= 0`` (the retained factor is clamped to
    ``[0, 1]`` and savings are clamped at 0, so a factor implying negative
    savings can never produce one).

The XGBoost forecaster (task 4.2) is *not* imported here; the baseline forecast
values are passed in as plain arguments to keep this module independent and
avoid an import-time race with the parallel forecaster work.
"""

from __future__ import annotations

from typing import Literal, Mapping, Sequence, Union

from backend.core.config import load_policy
from backend.schemas.recommendation import (
    ForecastComponent,
    OptimizationImpactForecast,
)

# A factor specification per dimension may be a scalar (e.g. ``1.0``) or a
# ``[low, high]`` range. ``FactorMap`` maps a dimension name to such a spec.
FactorValue = Union[float, int, Sequence[float]]
FactorMap = Mapping[str, FactorValue]

DIMENSIONS = ("cost", "energy", "carbon")

#: Where in a ``[low, high]`` factor range to evaluate when collapsing to a
#: single deterministic point.
RangePoint = Literal["min", "mid", "max"]


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp ``value`` into the inclusive ``[lo, hi]`` interval."""
    return max(lo, min(hi, value))


def _resolve_point(spec: FactorValue, point: RangePoint) -> float:
    """Collapse a factor spec (scalar or ``[low, high]`` range) to one float.

    The resulting factor is clamped to ``[0.0, 1.0]`` so it always represents a
    valid retained fraction. A factor above 1 (which would imply the action
    *increases* the dimension and therefore yields negative savings) is treated
    as "no savings" by clamping to 1.0.
    """
    if isinstance(spec, (int, float)):
        factor = float(spec)
    else:
        values = list(spec)
        if not values:
            raise ValueError("factor range must contain at least one value")
        low = float(min(values))
        high = float(max(values))
        if point == "min":
            factor = low
        elif point == "max":
            factor = high
        else:  # "mid"
            factor = (low + high) / 2.0
    return _clamp(factor, 0.0, 1.0)


def get_optimization_factors(recommendation_type: str) -> FactorMap:
    """Return the cost/energy/carbon factor spec for a recommendation type.

    Looks the type up in ``recommendation_rules.json``'s
    ``optimization_factors_reference`` table.

    Raises:
        KeyError: if the recommendation type has no defined factors.
    """
    policy = load_policy("recommendation_rules")
    reference = policy.get("optimization_factors_reference", {})
    if recommendation_type not in reference:
        raise KeyError(
            f"No optimization factors defined for recommendation_type "
            f"'{recommendation_type}'"
        )
    return reference[recommendation_type]


def _dimension_savings(without: float, factor: float) -> tuple[float, float]:
    """Return ``(after, savings)`` for one dimension given a retained factor.

    ``after = without x factor`` and ``savings = without - after``. Because the
    factor is in ``[0, 1]`` and ``without`` is non-negative, ``savings`` is
    guaranteed non-negative; it is additionally clamped at 0 for defensiveness
    against floating-point noise, with ``after`` recomputed so that
    ``without - after == savings`` holds exactly.
    """
    after = without * factor
    savings = without - after
    if savings < 0.0:
        savings = 0.0
        after = without
    return after, savings


def compute_optimization_impact(
    *,
    cost_30d: float,
    energy_kwh_30d: float,
    carbon_kgco2e_30d: float,
    recommendation_type: str | None = None,
    optimization_factors: FactorMap | None = None,
    range_point: RangePoint = "mid",
) -> OptimizationImpactForecast:
    """Compute the before / after / savings optimization impact forecast.

    Args:
        cost_30d: Baseline (no-action) 30-day cost forecast in USD.
        energy_kwh_30d: Baseline 30-day energy forecast in kWh.
        carbon_kgco2e_30d: Baseline 30-day carbon forecast in kgCO2e.
        recommendation_type: The recommendation type whose factors to apply
            (resolved from ``recommendation_rules.json``). Ignored when
            ``optimization_factors`` is supplied.
        optimization_factors: Explicit per-dimension factor spec (overrides
            ``recommendation_type``). Must provide ``cost``, ``energy`` and
            ``carbon`` entries.
        range_point: Which point of a ``[low, high]`` factor range to use
            (``"min"`` / ``"mid"`` / ``"max"``). Defaults to ``"mid"``.

    Returns:
        An :class:`OptimizationImpactForecast` with consistent, non-negative
        savings for every dimension.

    Raises:
        ValueError: if neither ``recommendation_type`` nor
            ``optimization_factors`` is provided, if a baseline forecast value
            is negative, or if a required dimension factor is missing.
        KeyError: if ``recommendation_type`` has no defined factors.
    """
    if optimization_factors is None:
        if recommendation_type is None:
            raise ValueError(
                "Provide either recommendation_type or optimization_factors"
            )
        optimization_factors = get_optimization_factors(recommendation_type)

    baseline = {
        "cost": float(cost_30d),
        "energy": float(energy_kwh_30d),
        "carbon": float(carbon_kgco2e_30d),
    }
    for dim, value in baseline.items():
        if value < 0.0:
            raise ValueError(f"baseline {dim} forecast must be non-negative")

    after: dict[str, float] = {}
    savings: dict[str, float] = {}
    for dim in DIMENSIONS:
        if dim not in optimization_factors:
            raise ValueError(f"optimization_factors missing dimension '{dim}'")
        factor = _resolve_point(optimization_factors[dim], range_point)
        after[dim], savings[dim] = _dimension_savings(baseline[dim], factor)

    return OptimizationImpactForecast(
        forecast_without_action=ForecastComponent(
            cost_30d=baseline["cost"],
            energy_30d_kwh=baseline["energy"],
            carbon_30d_kgco2e=baseline["carbon"],
        ),
        forecast_after_action=ForecastComponent(
            cost_30d=after["cost"],
            energy_30d_kwh=after["energy"],
            carbon_30d_kgco2e=after["carbon"],
        ),
        projected_savings=ForecastComponent(
            cost_30d=savings["cost"],
            energy_30d_kwh=savings["energy"],
            carbon_30d_kgco2e=savings["carbon"],
        ),
    )
