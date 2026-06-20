"""Dimension scoring engine (task 7.2).

Computes the per-workload :class:`DimensionScores` that drive the dashboard
**matrix heatmap**: a 0-100 numeric score and a green/yellow/red/gray state for
each of the six dimensions — Security, Energy, Carbon, Cost, Performance, and
Monitoring (spec 07 §A4, Requirement 12.4).

Design notes
------------
- Each dimension starts at a perfect 100 and accrues *deductions* derived from
  the workload's latest :class:`TelemetrySnapshot`. The Security deduction
  ladder mirrors the Security_Score formula in spec 07 §A3
  (Critical −25 / High −15 / Medium −5 / Low −2). The other dimensions use
  cumulative inefficiency / saturation deductions in the same spirit.
- Open :class:`Issue` objects for the workload further depress the dimension
  matching the issue's category, using the same severity deduction ladder, so
  detected problems are reflected in the matrix.
- The mapping from numeric score to state is the single source of truth in
  :func:`state_for_score`: ``>= 75`` green, ``50-74`` yellow, ``< 50`` red, and
  ``None`` (no telemetry / insufficient data) gray.
- Scoring is **deterministic**: identical inputs always produce identical
  scores, with no reliance on wall-clock time or randomness.

The module exposes both a pure function (:func:`compute_dimension_scores`,
telemetry + issues in, scores out) and a service-backed convenience wrapper
(:func:`score_workload`) that loads the latest telemetry and open issues for a
workload id.
"""

from __future__ import annotations

import logging

from backend.schemas.scoring import DimensionScore, DimensionScores, DimensionState
from backend.schemas.telemetry import TelemetrySnapshot

logger = logging.getLogger("clover.scoring.dimension")

# State thresholds (spec 07 §A4 / Requirement 12.4).
GREEN_THRESHOLD = 75.0
YELLOW_THRESHOLD = 50.0

# Severity deduction ladder shared by the Security formula and issue impact
# (spec 07 §A3 Security_Score).
SEVERITY_DEDUCTION: dict[str, float] = {
    "critical": 25.0,
    "high": 15.0,
    "medium": 5.0,
    "low": 2.0,
}

# Issue category -> dimension attribute name. ``cost_energy_carbon`` issues
# touch all three GreenOps/cost dimensions.
_CATEGORY_TO_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "security": ("security",),
    "energy": ("energy",),
    "carbon": ("carbon",),
    "cost": ("cost",),
    "performance": ("performance",),
    "monitoring": ("monitoring",),
    "cost_energy_carbon": ("cost", "energy", "carbon"),
}

# The six dimensions, in matrix-display order.
DIMENSIONS: tuple[str, ...] = (
    "security",
    "energy",
    "carbon",
    "cost",
    "performance",
    "monitoring",
)


def state_for_score(score: float | None) -> DimensionState:
    """Map a numeric score (or ``None``) to a dimension state.

    ``None`` represents insufficient data and maps to ``gray``. Otherwise:
    ``>= 75`` -> green, ``50 <= score < 75`` -> yellow, ``< 50`` -> red.
    """
    if score is None:
        return "gray"
    if score >= GREEN_THRESHOLD:
        return "green"
    if score >= YELLOW_THRESHOLD:
        return "yellow"
    return "red"


def _clamp(value: float) -> float:
    """Clamp a raw score into the inclusive [0, 100] band, rounded to 1dp."""
    return round(max(0.0, min(100.0, value)), 1)


def _make_score(value: float | None) -> DimensionScore:
    """Build a :class:`DimensionScore`, mapping ``None`` to a gray zero score."""
    if value is None:
        return DimensionScore(score=0.0, state="gray")
    clamped = _clamp(value)
    return DimensionScore(score=clamped, state=state_for_score(clamped))


# --------------------------------------------------------------------------- #
# Per-dimension deduction formulas (telemetry -> raw 0-100 score)
# --------------------------------------------------------------------------- #
def _security_raw(t: TelemetrySnapshot) -> float:
    """Security posture: start 100, deduct for vulns and exposure."""
    deductions = SEVERITY_DEDUCTION.get(t.vulnerability_severity, 0.0)
    # Each known critical vulnerability adds to the deduction (capped).
    deductions += min(t.critical_vulnerability_count * 10.0, 40.0)
    if t.public_exposure:
        deductions += 20.0
    if t.public_storage:
        deductions += 15.0
    if t.access_anomaly_detected:
        deductions += 20.0
    return 100.0 - deductions


def _energy_raw(t: TelemetrySnapshot) -> float:
    """Energy efficiency: deduct for idle/underutilized always-on compute."""
    deductions = 0.0
    if t.cpu_usage_percent < 10.0:
        deductions += 30.0  # effectively idle
    elif t.cpu_usage_percent < 30.0:
        deductions += 15.0  # underutilized
    # Always-on (near 24h) low-utilization workloads waste energy.
    if t.runtime_hours_24h >= 20.0 and t.cpu_usage_percent < 30.0:
        deductions += 10.0
    if t.energy_kwh_24h > 50.0:
        deductions += 10.0
    return 100.0 - deductions


def _carbon_raw(t: TelemetrySnapshot) -> float:
    """Carbon footprint: deduct for high emissions and dirty grid intensity."""
    deductions = 0.0
    # Emissions volume (kg CO2e/24h): ~1 pt per kg, capped.
    deductions += min(t.carbon_kgco2e_24h, 60.0)
    # Grid carbon intensity (gCO2/kWh).
    if t.carbon_intensity_gco2_per_kwh > 500.0:
        deductions += 20.0
    elif t.carbon_intensity_gco2_per_kwh > 400.0:
        deductions += 10.0
    return 100.0 - deductions


def _cost_raw(t: TelemetrySnapshot) -> float:
    """Cost efficiency: deduct for spend and idle-but-paid resources."""
    deductions = 0.0
    # Idle workloads that still cost money are pure waste.
    if t.cpu_usage_percent < 10.0 and t.cost_24h > 0.0:
        deductions += 30.0
    elif t.cpu_usage_percent < 30.0 and t.cost_24h > 0.0:
        deductions += 15.0
    # Absolute daily spend bands.
    if t.cost_24h > 200.0:
        deductions += 25.0
    elif t.cost_24h > 100.0:
        deductions += 15.0
    elif t.cost_24h > 50.0:
        deductions += 5.0
    return 100.0 - deductions


def _performance_raw(t: TelemetrySnapshot) -> float:
    """Performance health: deduct for errors, latency and saturation."""
    deductions = 0.0
    if t.error_rate_percent > 5.0:
        deductions += 30.0
    elif t.error_rate_percent > 1.0:
        deductions += 10.0
    if t.latency_ms > 1000.0:
        deductions += 20.0
    elif t.latency_ms > 500.0:
        deductions += 10.0
    if t.cpu_usage_percent > 90.0:
        deductions += 20.0
    if t.memory_usage_percent > 90.0:
        deductions += 20.0
    return 100.0 - deductions


def _monitoring_raw(t: TelemetrySnapshot) -> float:
    """Monitoring coverage: full marks when enabled, zero when missing."""
    return 100.0 if t.monitoring_enabled else 0.0


def _apply_issue_deductions(
    raw: dict[str, float], issues: list[dict] | None
) -> dict[str, float]:
    """Depress dimensions that have open issues, by the severity ladder."""
    if not issues:
        return raw
    for issue in issues:
        category = issue.get("issue_category")
        severity = issue.get("severity")
        deduction = SEVERITY_DEDUCTION.get(severity, 0.0)
        if not deduction:
            continue
        for dimension in _CATEGORY_TO_DIMENSIONS.get(category, ()):  # type: ignore[arg-type]
            raw[dimension] = raw[dimension] - deduction
    return raw


def compute_dimension_scores(
    workload_id: str,
    telemetry: TelemetrySnapshot | None,
    issues: list[dict] | None = None,
) -> DimensionScores:
    """Compute the six :class:`DimensionScores` for a workload.

    When ``telemetry`` is ``None`` there is insufficient data, so every
    dimension is reported as ``gray``. Otherwise each dimension is scored from
    the snapshot and then further depressed by any open ``issues`` whose
    category maps to that dimension.
    """
    if telemetry is None:
        gray = _make_score(None)
        return DimensionScores(
            workload_id=workload_id,
            security=gray,
            energy=gray,
            carbon=gray,
            cost=gray,
            performance=gray,
            monitoring=gray,
        )

    raw: dict[str, float] = {
        "security": _security_raw(telemetry),
        "energy": _energy_raw(telemetry),
        "carbon": _carbon_raw(telemetry),
        "cost": _cost_raw(telemetry),
        "performance": _performance_raw(telemetry),
        "monitoring": _monitoring_raw(telemetry),
    }
    raw = _apply_issue_deductions(raw, issues)

    return DimensionScores(
        workload_id=workload_id,
        security=_make_score(raw["security"]),
        energy=_make_score(raw["energy"]),
        carbon=_make_score(raw["carbon"]),
        cost=_make_score(raw["cost"]),
        performance=_make_score(raw["performance"]),
        monitoring=_make_score(raw["monitoring"]),
    )


def score_workload(workload_id: str, *, db_path: str | None = None) -> DimensionScores:
    """Load a workload's latest telemetry + open issues and score it.

    Returns all-``gray`` scores when no telemetry has been ingested yet. The
    service imports are local to avoid import-time cycles with the API layer.
    """
    from backend.services import issue_service, telemetry_service

    history = telemetry_service.get_telemetry_history(
        workload_id, limit=1, db_path=db_path
    )
    telemetry: TelemetrySnapshot | None = None
    if history:
        try:
            telemetry = TelemetrySnapshot(**history[0])
        except Exception:  # noqa: BLE001 - tolerate legacy/partial snapshots
            logger.warning("Could not parse latest telemetry for %s", workload_id)
            telemetry = None

    open_issues = [
        issue
        for issue in issue_service.list_issues(workload_id=workload_id, db_path=db_path)
        if issue.get("status") in issue_service.OPEN_STATUSES
    ]
    return compute_dimension_scores(workload_id, telemetry, open_issues)
