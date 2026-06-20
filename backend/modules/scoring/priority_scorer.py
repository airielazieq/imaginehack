"""Priority Score computation for the Scoring Engine (task 7.1).

Computes the 6-factor weighted ``Priority_Score`` (0-100, 1 decimal place) that
drives the composite heatmap. The score is a normalized weighted sum of six
factors, each derived to a normalized ``[0, 1]`` contribution where **higher
means more urgent** (redder on the heatmap):

================== ============================================================
Factor             Derivation (all clamped to ``[0, 1]``, higher = worse)
================== ============================================================
security_severity  max of (a) the latest security telemetry signal — vulnerability
                   severity scaled, bumped by public exposure / public storage /
                   access anomaly — and (b) the latest security-category Issue's
                   severity. Unavailable only when there is neither telemetry nor
                   any issue for the workload.
energy_waste       under-utilization over a long runtime wastes energy:
                   ``runtime_fraction * (1 - cpu_utilization)``, bumped when an
                   open energy/carbon/cost_energy_carbon Issue exists. Needs
                   telemetry.
cost_waste         the energy-waste idle signal combined with cost-forecast
                   growth (``cost_30d_forecast`` exceeding a flat extrapolation
                   of ``cost_24h``). Needs telemetry.
workflow_criticality  workload ``workflow_criticality`` mapped
                   low=0.25 / medium=0.5 / high=0.75 / critical=1.0. Needs the
                   workload record.
environment_type   workload ``environment`` mapped development=0.1 / testing=0.3
                   / staging=0.6 / production=1.0. Needs the workload record.
self_healing_safety  how *unsafe* the situation is to auto-heal — derived from
                   the latest Recommendation's required execution mode
                   (auto_fix=0.15 / user_approval_required=0.6 /
                   human_escalation_required=1.0) and risk level. Drops to 0.0
                   once a remediation has completed & verification passed. Needs
                   a Recommendation (or Remediation).
================== ============================================================

Weighted score::

    score = 100 * Σ_i ( effective_weight_i * factor_i )

Weights are loaded from ``rules/scoring_weights.json`` and **must sum to 1.0**
(Requirement 12.2) — an invalid configuration raises :class:`ValueError`.

**Missing factors** (Requirement 12.x / spec 07 A2): when a factor cannot be
derived (no telemetry, no workload, no recommendation, ...), its weight is
redistributed proportionally across the available factors so the remaining
weights still sum to 1.0. The missing factor names are reported in
``PriorityScore.unavailable_factors`` and their stored factor value is ``0.0``.

The score is **deterministic**: identical inputs + weights produce an identical
score (spec 07 A2).

Two public entry points:

- :func:`compute_for_workload` - synchronous; builds the :class:`PriorityScore`
  for a workload from its latest persisted state (used by the API/dashboard).
- :func:`recompute_and_emit` - async; computes the score and publishes a
  ``SCORE_UPDATED`` event.

:func:`register_subscriptions` wires recomputation to ``ISSUE_DETECTED``,
``RECOMMENDATION_GENERATED`` and ``REMEDIATION_COMPLETED`` (idempotent), and is
called from the application lifespan.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from backend.core.config import load_policy
from backend.core.event_bus import Event, EventType, event_bus
from backend.schemas.scoring import PriorityScore
from backend.services import (
    issue_service,
    recommendation_service,
    remediation_service,
    telemetry_service,
    workload_service,
)

logger = logging.getLogger("clover.scoring.priority")

# The six factor names, in canonical order.
FACTOR_NAMES: tuple[str, ...] = (
    "security_severity",
    "energy_waste",
    "cost_waste",
    "workflow_criticality",
    "environment_type",
    "self_healing_safety",
)

# Acceptable floating-point tolerance for the "weights sum to 1.0" check.
_WEIGHT_SUM_TOLERANCE = 1e-6

# --- Mapping tables (deterministic) ----------------------------------------- #
_VULN_SEVERITY: dict[str, float] = {
    "none": 0.0,
    "low": 0.2,
    "medium": 0.5,
    "high": 0.75,
    "critical": 1.0,
}
_ISSUE_SEVERITY: dict[str, float] = {
    "low": 0.25,
    "medium": 0.5,
    "high": 0.75,
    "critical": 1.0,
}
_CRITICALITY: dict[str, float] = {
    "low": 0.25,
    "medium": 0.5,
    "high": 0.75,
    "critical": 1.0,
}
_ENVIRONMENT: dict[str, float] = {
    "development": 0.1,
    "testing": 0.3,
    "staging": 0.6,
    "production": 1.0,
}
_EXECUTION_MODE: dict[str, float] = {
    "auto_fix": 0.15,
    "user_approval_required": 0.6,
    "human_escalation_required": 1.0,
}
_RISK_LEVEL: dict[str, float] = {
    "low": 0.2,
    "medium": 0.5,
    "high": 0.75,
    "critical": 1.0,
}

_SECURITY_CATEGORIES = {"security"}
_ENERGY_CATEGORIES = {"energy", "carbon", "cost_energy_carbon"}
_COST_CATEGORIES = {"cost", "cost_energy_carbon"}


def _clamp01(value: float) -> float:
    """Clamp a value into the closed ``[0, 1]`` interval."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Weight loading + validation (Requirement 12.2)
# --------------------------------------------------------------------------- #
def load_weights() -> dict[str, float]:
    """Load and validate the 6 factor weights from ``scoring_weights.json``.

    Returns the ``{factor_name: weight}`` mapping. Raises :class:`ValueError`
    when the configuration is invalid:

    - a factor weight is missing,
    - the six weights do not sum to exactly 1.0 (within a tiny tolerance),
    - the elevated-factor constraint is violated (task 20.1 / spec 07 §A1):
      ``security_severity`` and ``environment_type`` each **must** be at least
      ``1.5x`` the average of the other four factor weights.

    The checks run in that order so the most specific failure surfaces first
    (missing key -> bad sum -> elevated constraint).
    """
    policy = load_policy("scoring_weights")
    raw = policy.get("weights", {})

    weights: dict[str, float] = {}
    for name in FACTOR_NAMES:
        if name not in raw:
            raise ValueError(f"scoring_weights.json is missing weight '{name}'")
        weights[name] = float(raw[name])

    total = sum(weights.values())
    if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise ValueError(
            f"scoring_weights.json factor weights must sum to 1.0, got {total:.6f}"
        )

    _enforce_elevated_constraint(weights, policy)
    return weights


def _elevated_config(policy: dict) -> tuple[list[str], float]:
    """Resolve the elevated-factor names and required multiplier from policy."""
    constraints = policy.get("constraints", {}) or {}
    elevated = constraints.get("elevated_factors") or [
        "security_severity",
        "environment_type",
    ]
    multiplier = float(constraints.get("elevated_min_multiplier_of_others_avg", 1.5))
    return list(elevated), multiplier


def _enforce_elevated_constraint(weights: dict[str, float], policy: dict) -> None:
    """Reject configs where elevated factors are under-weighted (task 20.1).

    The constraint (spec 07 §A1): ``security_severity`` and ``environment_type``
    must each be ``>= 1.5x`` the average of the other four factor weights.
    Raises :class:`ValueError` when violated so an invalid weight configuration
    is rejected rather than silently producing a skewed score.
    """
    elevated, multiplier = _elevated_config(policy)

    others = [w for name, w in weights.items() if name not in elevated]
    if not others:
        return
    others_avg = sum(others) / len(others)
    required = multiplier * others_avg
    for name in elevated:
        if weights.get(name, 0.0) + _WEIGHT_SUM_TOLERANCE < required:
            raise ValueError(
                f"scoring_weights.json elevated-factor constraint violated: "
                f"weight['{name}']={weights.get(name, 0.0):.4f} must be >= "
                f"{multiplier:.1f}x the average of the other factors "
                f"({required:.4f})"
            )


# --------------------------------------------------------------------------- #
# Context resolution (latest persisted state for a workload)
# --------------------------------------------------------------------------- #
def _latest_telemetry(workload_id: str, *, db_path: str | None = None) -> Optional[dict]:
    history = telemetry_service.get_telemetry_history(
        workload_id, limit=1, db_path=db_path
    )
    return history[0] if history else None


def _latest_issue(workload_id: str, *, db_path: str | None = None) -> Optional[dict]:
    issues = issue_service.list_issues(workload_id=workload_id, db_path=db_path)
    return issues[0] if issues else None


def _latest_security_issue(workload_id: str, *, db_path: str | None = None) -> Optional[dict]:
    issues = issue_service.list_issues(workload_id=workload_id, db_path=db_path)
    for issue in issues:
        if issue.get("issue_category") in _SECURITY_CATEGORIES:
            return issue
    return None


def _has_open_issue_in(
    workload_id: str, categories: set[str], *, db_path: str | None = None
) -> bool:
    issues = issue_service.list_issues(workload_id=workload_id, db_path=db_path)
    return any(issue.get("issue_category") in categories for issue in issues)


def _latest_recommendation(workload_id: str, *, db_path: str | None = None) -> Optional[dict]:
    recs = recommendation_service.list_recommendations(
        workload_id=workload_id, db_path=db_path
    )
    return recs[0] if recs else None


def _latest_remediation(workload_id: str, *, db_path: str | None = None) -> Optional[dict]:
    rems = remediation_service.list_remediations(
        workload_id=workload_id, db_path=db_path
    )
    return rems[0] if rems else None


# --------------------------------------------------------------------------- #
# Factor derivations -> Optional[float] in [0, 1] (None == unavailable)
# --------------------------------------------------------------------------- #
def _runtime_idle_signal(telemetry: dict) -> float:
    """Idle/over-provisioning signal: long runtime at low utilization wastes."""
    cpu = float(telemetry.get("cpu_usage_percent", 0.0))
    runtime = float(telemetry.get("runtime_hours_24h", 0.0))
    utilization = _clamp01(cpu / 100.0)
    runtime_fraction = _clamp01(runtime / 24.0)
    return _clamp01(runtime_fraction * (1.0 - utilization))


def _derive_security_severity(
    telemetry: Optional[dict], security_issue: Optional[dict]
) -> Optional[float]:
    """Security urgency from telemetry posture and/or the latest security Issue."""
    if telemetry is None and security_issue is None:
        return None

    score = 0.0
    if telemetry is not None:
        score = _VULN_SEVERITY.get(telemetry.get("vulnerability_severity", "none"), 0.0)
        if telemetry.get("public_exposure"):
            score = max(score, 0.6)
        if telemetry.get("public_storage"):
            score = max(score, 0.7)
        if telemetry.get("access_anomaly_detected"):
            score = max(score, 0.5)
        if not telemetry.get("monitoring_enabled", True):
            score = max(score, 0.3)
    if security_issue is not None:
        score = max(score, _ISSUE_SEVERITY.get(security_issue.get("severity", "low"), 0.0))
    return _clamp01(score)


def _derive_energy_waste(
    telemetry: Optional[dict], has_energy_issue: bool
) -> Optional[float]:
    """Energy waste from under-utilization, bumped by an open energy issue."""
    if telemetry is None:
        return None
    waste = _runtime_idle_signal(telemetry)
    if has_energy_issue:
        waste = max(waste, 0.6)
    return _clamp01(waste)


def _derive_cost_waste(
    telemetry: Optional[dict], has_cost_issue: bool
) -> Optional[float]:
    """Cost waste from under-utilization plus 30-day forecast growth."""
    if telemetry is None:
        return None
    waste = _runtime_idle_signal(telemetry)

    cost_24h = float(telemetry.get("cost_24h", 0.0))
    forecast_30d = float(telemetry.get("cost_30d_forecast", 0.0))
    if cost_24h > 0.0:
        # Flat extrapolation baseline; growth above it signals cost creep.
        baseline = cost_24h * 30.0
        growth = (forecast_30d - baseline) / baseline if baseline > 0 else 0.0
        # Map up to +100% growth -> 1.0.
        waste = max(waste, _clamp01(growth))

    if has_cost_issue:
        waste = max(waste, 0.6)
    return _clamp01(waste)


def _derive_workflow_criticality(workload: Optional[dict]) -> Optional[float]:
    if workload is None:
        return None
    return _CRITICALITY.get(workload.get("workflow_criticality", "low"), 0.25)


def _derive_environment_type(workload: Optional[dict]) -> Optional[float]:
    if workload is None:
        return None
    return _ENVIRONMENT.get(workload.get("environment", "development"), 0.1)


def _derive_self_healing_safety(
    recommendation: Optional[dict], remediation: Optional[dict]
) -> Optional[float]:
    """How *unsafe* the situation is to auto-heal (higher = needs a human).

    Resolved once a remediation has completed with verification passed (and no
    rollback), in which case the factor drops to 0.0.
    """
    if remediation is not None:
        if (
            remediation.get("execution_status") == "completed"
            and remediation.get("verification_result") == "passed"
            and not remediation.get("rollback_triggered")
        ):
            return 0.0

    if recommendation is None:
        return None

    mode_score = _EXECUTION_MODE.get(
        recommendation.get("required_execution_mode", "user_approval_required"), 0.6
    )
    risk_score = _RISK_LEVEL.get(recommendation.get("risk_level", "medium"), 0.5)
    return _clamp01(max(mode_score, risk_score))


# --------------------------------------------------------------------------- #
# Weighted aggregation with proportional missing-factor redistribution
# --------------------------------------------------------------------------- #
def _aggregate(
    factors: dict[str, Optional[float]], weights: dict[str, float]
) -> tuple[float, list[str]]:
    """Combine derived factors into a 0-100 score with weight redistribution.

    Missing factors (``None``) have their weight redistributed proportionally
    across the available factors so the effective weights still sum to 1.0.

    Returns ``(score_0_100, unavailable_factor_names)``.
    """
    available = {name: value for name, value in factors.items() if value is not None}
    unavailable = sorted(name for name, value in factors.items() if value is None)

    if not available:
        # Nothing to score on; everything is unavailable.
        return 0.0, sorted(factors.keys())

    available_weight_total = sum(weights[name] for name in available)
    if available_weight_total <= 0.0:
        return 0.0, unavailable

    score01 = 0.0
    for name, value in available.items():
        effective_weight = weights[name] / available_weight_total
        score01 += effective_weight * value

    score = round(_clamp01(score01) * 100.0, 1)
    return score, unavailable


# --------------------------------------------------------------------------- #
# Public: synchronous Priority Score computation
# --------------------------------------------------------------------------- #
def compute_for_workload(
    workload_id: str,
    *,
    weights: dict[str, float] | None = None,
    db_path: str | None = None,
) -> PriorityScore:
    """Compute the :class:`PriorityScore` for a workload from its latest state.

    Pulls the latest persisted telemetry, issue, recommendation and remediation
    for ``workload_id``, derives the six factors, and aggregates them into a
    0-100 score (1 dp) using the configured weights. Factors that cannot be
    derived are listed in ``unavailable_factors`` and their weight is
    redistributed across the available factors.

    Deterministic for a fixed persisted state + weights.
    """
    if weights is None:
        weights = load_weights()

    workload = workload_service.get_workload(workload_id, db_path=db_path)
    telemetry = _latest_telemetry(workload_id, db_path=db_path)
    latest_issue = _latest_issue(workload_id, db_path=db_path)
    security_issue = _latest_security_issue(workload_id, db_path=db_path)
    recommendation = _latest_recommendation(workload_id, db_path=db_path)
    remediation = _latest_remediation(workload_id, db_path=db_path)

    has_energy_issue = _has_open_issue_in(
        workload_id, _ENERGY_CATEGORIES, db_path=db_path
    )
    has_cost_issue = _has_open_issue_in(
        workload_id, _COST_CATEGORIES, db_path=db_path
    )

    factors: dict[str, Optional[float]] = {
        "security_severity": _derive_security_severity(telemetry, security_issue),
        "energy_waste": _derive_energy_waste(telemetry, has_energy_issue),
        "cost_waste": _derive_cost_waste(telemetry, has_cost_issue),
        "workflow_criticality": _derive_workflow_criticality(workload),
        "environment_type": _derive_environment_type(workload),
        "self_healing_safety": _derive_self_healing_safety(recommendation, remediation),
    }

    score, unavailable = _aggregate(factors, weights)

    detection_timestamp = _resolve_detection_timestamp(latest_issue, telemetry)

    return PriorityScore(
        workload_id=workload_id,
        score=score,
        security_severity=factors["security_severity"] or 0.0,
        energy_waste=factors["energy_waste"] or 0.0,
        cost_waste=factors["cost_waste"] or 0.0,
        workflow_criticality=factors["workflow_criticality"] or 0.0,
        environment_type=factors["environment_type"] or 0.0,
        self_healing_safety=factors["self_healing_safety"] or 0.0,
        unavailable_factors=unavailable,
        detection_timestamp=detection_timestamp,
        computed_at=_utcnow(),
    )


def _resolve_detection_timestamp(
    latest_issue: Optional[dict], telemetry: Optional[dict]
) -> datetime:
    """Pick the detection timestamp used for ranking (spec A2 tiebreaker)."""
    for source, key in ((latest_issue, "detected_at"), (telemetry, "timestamp")):
        if source and source.get(key):
            try:
                text = str(source[key])
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                dt = datetime.fromisoformat(text)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return _utcnow()


# --------------------------------------------------------------------------- #
# Ranking + tiebreaker (task 20.1 / spec 07 §A2)
# --------------------------------------------------------------------------- #
def ranking_key(score: PriorityScore) -> tuple[float, datetime]:
    """Sort key implementing the documented ranking + tiebreaker.

    Workloads are ranked **highest Priority_Score first**; when two scores are
    equal, the workload with the **earlier ``detection_timestamp`` ranks
    higher** (spec 07 §A2). Used as the ``key`` for an ascending ``sort`` /
    ``min``: the negated score puts the largest score first and the raw
    timestamp puts the earliest detection first within a tie.
    """
    return (-score.score, score.detection_timestamp)


def rank_scores(scores: list[PriorityScore]) -> list[PriorityScore]:
    """Return ``scores`` ordered most-urgent-first with the timestamp tiebreaker.

    Stable, deterministic ordering: descending Priority_Score, then ascending
    ``detection_timestamp`` (earlier detection ranks higher) on ties.
    """
    return sorted(scores, key=ranking_key)
# --------------------------------------------------------------------------- #
async def recompute_and_emit(
    workload_id: str,
    *,
    correlation_id: str | None = None,
    db_path: str | None = None,
) -> PriorityScore:
    """Recompute the Priority Score for a workload and publish ``SCORE_UPDATED``.

    Returns the freshly computed :class:`PriorityScore`. Used by the event
    handlers (recompute within 5s of an underlying state change — Requirement
    12.3) and available for direct invocation.
    """
    score = compute_for_workload(workload_id, db_path=db_path)
    event = Event(
        event_type=EventType.SCORE_UPDATED,
        payload={
            "workload_id": workload_id,
            "score": score.score,
            "priority_score": score.model_dump(mode="json"),
        },
    )
    if correlation_id:
        event.correlation_id = correlation_id
    await event_bus.publish(event)
    logger.debug("Recomputed priority score for %s -> %.1f", workload_id, score.score)
    return score


# --------------------------------------------------------------------------- #
# Event subscription (idempotent)
# --------------------------------------------------------------------------- #
async def _on_state_change(event: Event) -> None:
    """Recompute the Priority Score when underlying state changes.

    Handles ``ISSUE_DETECTED``, ``RECOMMENDATION_GENERATED`` and
    ``REMEDIATION_COMPLETED`` — every one of these carries ``workload_id`` in
    its payload.
    """
    payload = event.payload or {}
    workload_id = payload.get("workload_id")
    if not workload_id:
        return
    try:
        await recompute_and_emit(workload_id, correlation_id=event.correlation_id)
    except Exception:  # noqa: BLE001 - isolate the subscriber from the bus
        logger.exception("Failed to recompute priority score for %s", workload_id)


_TRIGGER_EVENTS: tuple[EventType, ...] = (
    EventType.ISSUE_DETECTED,
    EventType.RECOMMENDATION_GENERATED,
    EventType.REMEDIATION_COMPLETED,
)

_subscribed = False


def register_subscriptions() -> None:
    """Subscribe the scorer to Issue/Recommendation/Remediation events.

    Idempotent: repeated calls (e.g. across test setups or re-imports) register
    the handlers at most once. Called from the application lifespan.
    """
    global _subscribed
    if _subscribed:
        return
    for event_type in _TRIGGER_EVENTS:
        event_bus.subscribe(event_type, _on_state_change)
    _subscribed = True
    logger.info(
        "Priority scorer subscribed to %s",
        ", ".join(e.value for e in _TRIGGER_EVENTS),
    )
