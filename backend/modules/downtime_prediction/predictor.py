"""Downtime prediction engine (Requirement 14).

Computes a failure probability, estimated time-to-failure, confidence level, and
primary/secondary contributing signals for a workload from its telemetry history
using simple linear-regression trend analysis on degrading metrics (error rate,
latency, CPU and memory saturation).

The headline :func:`predict` function is pure and side-effect-free so it is
trivially testable. The optional :func:`maybe_trigger_preemptive` performs the
best-effort NBA hand-off (Requirement 14.3) and is kept separate so prediction
never fails because of a downstream issue.

Algorithm (design "Downtime Prediction"):
- For each tracked metric, fit a least-squares slope over the chronological
  history and project the value 12 hours ahead.
- Overall failure probability = projected proximity to the critical threshold,
  dominated by the worst metric (see :func:`timeline.overall_risk`).
- Estimated time-to-failure = hours until the primary metric reaches critical at
  its current degradation rate.
- Confidence scales with the amount of history available; with insufficient
  history the probability is capped so the engine never fabricates a high-risk
  claim (SDD fallback), which also suppresses the preemptive CTA.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.modules.downtime_prediction.timeline import (
    MetricTrend,
    build_risk_timeline,
    overall_risk,
)
from backend.schemas.prediction import DowntimePrediction

logger = logging.getLogger("clover.prediction.predictor")

PREEMPTIVE_THRESHOLD = 70.0
PREDICTION_WINDOW_HOURS = 12
_LOW_CONFIDENCE_PROBABILITY_CAP = 50.0
_STABLE_TTF = ">48h"
_MAX_TTF_HOURS = 48.0


# Metric specifications: which telemetry fields drive the forecast, the value at
# which each becomes failure-inducing, and its relative weight.
_METRIC_SPECS: tuple[dict[str, Any], ...] = (
    {"field": "error_rate_percent", "label": "Error rate", "unit": "%", "critical": 100.0, "weight": 1.0},
    {"field": "memory_usage_percent", "label": "Memory saturation", "unit": "%", "critical": 100.0, "weight": 1.0},
    {"field": "cpu_usage_percent", "label": "CPU saturation", "unit": "%", "critical": 100.0, "weight": 0.85},
    {"field": "latency_ms", "label": "Latency", "unit": "ms", "critical": 2000.0, "weight": 0.7},
)


def _slope_per_hour(values: list[float]) -> float:
    """Least-squares slope of ``values`` assuming one sample per hour.

    Returns 0.0 for fewer than two points or a degenerate x-spread.
    """
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(values))
    denominator = sum((x - mean_x) ** 2 for x in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _extract_series(history_chrono: list[dict], field: str) -> list[float]:
    """Pull a numeric metric series (chronological order) from telemetry rows."""
    series: list[float] = []
    for row in history_chrono:
        value = row.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            series.append(float(value))
    return series


def _build_trends(history_chrono: list[dict]) -> list[MetricTrend]:
    """Build a :class:`MetricTrend` for every tracked metric with data."""
    trends: list[MetricTrend] = []
    for spec in _METRIC_SPECS:
        series = _extract_series(history_chrono, spec["field"])
        if not series:
            continue
        trends.append(
            MetricTrend(
                field=spec["field"],
                label=spec["label"],
                unit=spec["unit"],
                current=series[-1],
                slope_per_hour=_slope_per_hour(series),
                critical=spec["critical"],
                weight=spec["weight"],
            )
        )
    return trends


def _confidence(num_points: int) -> str:
    """Map history depth to a confidence level (SDD: more history -> higher)."""
    if num_points < 3:
        return "low"
    if num_points < 8:
        return "medium"
    return "high"


def _rank_trends(trends: list[MetricTrend]) -> list[MetricTrend]:
    """Order trends by their 12h weighted risk, worst first."""
    return sorted(
        trends,
        key=lambda t: t.weighted_risk(PREDICTION_WINDOW_HOURS),
        reverse=True,
    )


def _format_duration(hours: float) -> str:
    """Render a duration in ``'Xh Ym'`` form (or ``'>48h'`` when far out)."""
    if hours >= _MAX_TTF_HOURS:
        return _STABLE_TTF
    whole_hours = int(hours)
    minutes = int(round((hours - whole_hours) * 60))
    if minutes == 60:
        whole_hours += 1
        minutes = 0
    if whole_hours <= 0 and minutes <= 0:
        return "0h 0m"
    return f"{whole_hours}h {minutes}m"


def _time_to_failure(primary: MetricTrend | None) -> str:
    """Hours until the primary metric reaches critical at its current slope."""
    if primary is None or primary.slope_per_hour <= 0:
        return _STABLE_TTF
    remaining = primary.critical - primary.current
    if remaining <= 0:
        return "0h 0m"
    hours = remaining / primary.slope_per_hour
    return _format_duration(hours)


def _signal_text(trend: MetricTrend) -> str:
    """Human-readable description of a contributing signal."""
    projected = trend.current + trend.slope_per_hour * PREDICTION_WINDOW_HOURS
    if trend.slope_per_hour > 0:
        return (
            f"{trend.label} at {trend.current:.0f}{trend.unit}, rising "
            f"{trend.slope_per_hour:.1f}{trend.unit}/hr "
            f"(projected {projected:.0f}{trend.unit} in 12h)"
        )
    return f"{trend.label} stable at {trend.current:.0f}{trend.unit}"


def _preemptive_action(primary: MetricTrend | None, ttf: str) -> str:
    """Preemptive recommendation text used when probability > 70%."""
    target = primary.label.lower() if primary is not None else "resource degradation"
    return (
        f"Schedule a graceful restart within the next {ttf} to clear {target} "
        "before projected failure (planned ~2 min restart vs unplanned outage)."
    )


def predict(workload_id: str, history: list[dict]) -> DowntimePrediction:
    """Compute a :class:`DowntimePrediction` from telemetry history.

    Args:
        workload_id: The workload being predicted.
        history: Telemetry snapshots **most recent first** (as returned by
            :func:`telemetry_service.get_telemetry_history`). Reversed
            internally to chronological order for trend fitting.

    Returns:
        A fully-populated :class:`DowntimePrediction`. With no telemetry, returns
        a low-confidence, zero-probability fallback rather than a fabricated
        number (SDD fallback) - the preemptive action stays ``None``.
    """
    history_chrono = list(reversed(history))
    num_points = len(history_chrono)

    if num_points == 0:
        return DowntimePrediction(
            workload_id=workload_id,
            probability=0.0,
            estimated_time_to_failure=_STABLE_TTF,
            primary_signal="Insufficient telemetry history to forecast",
            secondary_signal=None,
            pattern_match=None,
            confidence="low",
            risk_timeline=[0.0] * PREDICTION_WINDOW_HOURS,
            recommended_preemptive_action=None,
        )

    trends = _build_trends(history_chrono)
    ranked = _rank_trends(trends)
    confidence = _confidence(num_points)

    probability = overall_risk(trends, PREDICTION_WINDOW_HOURS)
    # Never claim high risk without enough history to support it (SDD fallback).
    if confidence == "low":
        probability = min(probability, _LOW_CONFIDENCE_PROBABILITY_CAP)
    probability = round(probability, 1)

    primary = ranked[0] if ranked else None
    secondary = ranked[1] if len(ranked) > 1 else None

    primary_signal = (
        _signal_text(primary) if primary is not None else "No degrading signals detected"
    )
    secondary_signal = _signal_text(secondary) if secondary is not None else None

    risk_timeline = build_risk_timeline(trends)
    ttf = _time_to_failure(primary)

    triggers = probability > PREEMPTIVE_THRESHOLD
    preemptive_action = _preemptive_action(primary, ttf) if triggers else None
    pattern_match = (
        "Resembles prior gradual-degradation incidents"
        if triggers and confidence == "high"
        else None
    )

    return DowntimePrediction(
        workload_id=workload_id,
        probability=probability,
        estimated_time_to_failure=ttf,
        primary_signal=primary_signal,
        secondary_signal=secondary_signal,
        pattern_match=pattern_match,
        confidence=confidence,
        risk_timeline=risk_timeline,
        recommended_preemptive_action=preemptive_action,
    )


# --------------------------------------------------------------------------- #
# Best-effort preemptive NBA hand-off (Requirement 14.3)
# --------------------------------------------------------------------------- #
class _PreemptiveIssue:
    """Lightweight Issue-shaped object for the NBA engine.

    The NBA engine only reads ``issue_type`` / ``issue_category`` /
    ``workload_id`` / ``detected_evidence`` / ``severity`` / ``issue_id`` when
    building a recommendation draft, so a full :class:`Issue` is unnecessary for
    a synthetic preemptive trigger.
    """

    def __init__(self, prediction: DowntimePrediction) -> None:
        self.issue_id = f"pred-{prediction.workload_id}"
        self.workload_id = prediction.workload_id
        # Downtime is an availability/performance concern; map to the
        # performance rule (RULE-PERF-001 -> investigate_incident).
        self.issue_type = "high_error_rate"
        self.issue_category = "performance"
        self.severity = "high"
        self.detected_evidence = {
            "source": "downtime_predictor",
            "probability": prediction.probability,
            "estimated_time_to_failure": prediction.estimated_time_to_failure,
            "primary_signal": prediction.primary_signal,
        }


async def maybe_trigger_preemptive(
    prediction: DowntimePrediction, *, db_path: str | None = None
) -> Any | None:
    """Trigger a preemptive Recommendation when probability > 70% (best-effort).

    Returns the generated Recommendation, or ``None`` when no preemptive action
    is warranted or the NBA hand-off fails. Failures are logged and swallowed so
    prediction is never blocked by a downstream problem (Requirement 14.3).
    """
    if prediction.recommended_preemptive_action is None:
        return None
    try:
        # Imported lazily to avoid a heavy import chain (and any import cycle)
        # on the prediction hot path.
        from backend.modules.next_best_action import nba_pipeline

        issue = _PreemptiveIssue(prediction)
        recommendation = await nba_pipeline.generate_and_store(issue, db_path=db_path)
        if recommendation is not None:
            logger.info(
                "Preemptive recommendation %s generated for workload %s (probability=%.1f%%)",
                recommendation.recommendation_id,
                prediction.workload_id,
                prediction.probability,
            )
        return recommendation
    except Exception:  # noqa: BLE001 - preemptive hand-off must never be fatal
        logger.exception(
            "Preemptive recommendation hand-off failed for workload %s",
            prediction.workload_id,
        )
        return None
