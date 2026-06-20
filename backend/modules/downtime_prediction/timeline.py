"""12-point hourly risk timeline generation (Requirement 14.2).

Given the per-metric degradation trends computed by :mod:`predictor`, project
each metric forward hour-by-hour and report the workload's overall risk (0-100)
at hours 1 through 12. The timeline is consistent with the headline failure
probability: the 12th point reflects the same projected pressure that drives the
probability computation.
"""

from __future__ import annotations

from dataclasses import dataclass

TIMELINE_POINTS = 12


@dataclass(frozen=True)
class MetricTrend:
    """A single metric's degradation trend used for projection.

    Attributes:
        field: The telemetry field name (e.g. ``"memory_usage_percent"``).
        label: Human-readable signal label (e.g. ``"Memory saturation"``).
        unit: Display unit (e.g. ``"%"`` or ``"ms"``).
        current: Latest observed value.
        slope_per_hour: Least-squares slope (value change per hour); positive
            means the metric is degrading toward its critical threshold.
        critical: The value at which the metric is considered failure-inducing.
        weight: Relative contribution of this metric to overall risk (0-1).
    """

    field: str
    label: str
    unit: str
    current: float
    slope_per_hour: float
    critical: float
    weight: float

    def projected_proximity(self, hours: float) -> float:
        """Fraction (0-1) of the critical threshold reached ``hours`` ahead."""
        if self.critical <= 0:
            return 0.0
        projected = self.current + self.slope_per_hour * hours
        return _clamp(projected / self.critical, 0.0, 1.0)

    def weighted_risk(self, hours: float) -> float:
        """Weighted projected proximity (0-1) at the given horizon."""
        return self.weight * self.projected_proximity(hours)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def overall_risk(trends: list[MetricTrend], hours: float) -> float:
    """Overall workload risk (0-100) at a given horizon.

    Dominated by the worst (highest weighted) metric, with a smaller boost from
    the next-worst so that multiple simultaneously degrading signals raise risk.
    """
    if not trends:
        return 0.0
    weighted = sorted((t.weighted_risk(hours) for t in trends), reverse=True)
    primary = weighted[0]
    secondary = weighted[1] if len(weighted) > 1 else 0.0
    return round(_clamp(primary + 0.2 * secondary, 0.0, 1.0) * 100.0, 1)


def build_risk_timeline(trends: list[MetricTrend]) -> list[float]:
    """Return a 12-point hourly risk timeline (risk at hours 1..12).

    Each point is the overall risk (0-100) projected that many hours into the
    future. With no trends available, returns 12 zeros (graceful fallback).
    """
    return [overall_risk(trends, hour) for hour in range(1, TIMELINE_POINTS + 1)]
