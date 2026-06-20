"""SHAP explainer for the Isolation Forest detector (task 3.3).

Answers the explainability question from spec 04 §7 -- *which telemetry
features made this workload look abnormal/risky?* -- by computing per-feature
contributions for a single observation and surfacing the top 3-5 as
``XAIFactor`` entries (feature, value, plain-language impact). The result is the
``xai_explanation`` attached to every ``Issue`` (Requirements 2.2 and 4.2).

Two paths, both of which always return a valid ``XAIExplanation`` so the
detection pipeline never breaks:

1. **SHAP path** -- ``shap.TreeExplainer`` runs on the *same* fitted
   ``IsolationForest`` and the *same* 17-feature vector used by the detector
   (task 3.2). Factors are ranked by absolute SHAP value (descending) and the
   top few are returned with a human-readable impact string built from a
   feature->phrase lookup table combined with a high/low/enabled direction.

2. **Rule-based fallback** -- used when SHAP is not installed, the model is
   unavailable, or TreeExplainer raises. Features are ranked by their
   normalized deviation from a healthy reference (and by which boolean risk
   conditions fired), with ``method="rule-based feature contribution
   fallback"``.

The explainer deliberately reuses ``get_detector()`` so the model is loaded
once and the feature ordering stays identical to training/inference.

Design references: design.md "SHAP Explainer", spec 04 §7, spec 09.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.modules.detection_insight.isolation_forest import (
    FEATURE_COLUMNS,
    IsolationForestDetector,
    build_feature_vector,
    get_detector,
)
from backend.schemas.issue import XAIExplanation, XAIFactor
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Method labels + tuning
# --------------------------------------------------------------------------- #
SHAP_METHOD = "SHAP (TreeExplainer on Isolation Forest)"
FALLBACK_METHOD = "rule-based feature contribution fallback"

# Number of top contributing factors to surface (spec: top 3-5).
TOP_N = 5
MIN_FACTORS = 3

# Relative band around the healthy reference within which a numeric value is
# considered "typical" rather than high/low.
_TYPICAL_BAND = 0.15

# --------------------------------------------------------------------------- #
# Plain-language phrase for every feature in the 17-feature contract.
# --------------------------------------------------------------------------- #
FEATURE_PHRASES: dict[str, str] = {
    "cpu_usage_percent": "CPU utilization",
    "memory_usage_percent": "memory utilization",
    "runtime_hours_24h": "24-hour runtime",
    "storage_gb": "provisioned storage",
    "request_count_24h": "24-hour request volume",
    "error_rate_percent": "error rate",
    "latency_ms": "request latency",
    "cost_24h": "24-hour cost",
    "cost_30d_forecast": "projected 30-day cost",
    "energy_kwh_24h": "24-hour energy usage",
    "carbon_kgco2e_24h": "24-hour carbon emissions",
    "carbon_intensity_gco2_per_kwh": "grid carbon intensity",
    "environment": "deployment environment",
    "cloud_service_type": "cloud service type",
    "workflow_criticality": "workflow criticality",
    "public_exposure": "public network exposure",
    "monitoring_enabled": "monitoring coverage",
}

# Typical healthy values for the 12 numeric features. Used both to phrase the
# high/low direction in the SHAP path and to rank deviation in the fallback.
HEALTHY_REFERENCE: dict[str, float] = {
    "cpu_usage_percent": 45.0,
    "memory_usage_percent": 55.0,
    "runtime_hours_24h": 12.0,
    "storage_gb": 200.0,
    "request_count_24h": 50_000.0,
    "error_rate_percent": 0.5,
    "latency_ms": 150.0,
    "cost_24h": 30.0,
    "cost_30d_forecast": 900.0,
    "energy_kwh_24h": 15.0,
    "carbon_kgco2e_24h": 6.0,
    "carbon_intensity_gco2_per_kwh": 400.0,
}

# Boolean features: the value that represents the *risky* (anomalous) state.
_BOOLEAN_RISKY_STATE: dict[str, float] = {
    "public_exposure": 1.0,      # exposed == risky
    "monitoring_enabled": 0.0,   # monitoring off == risky
}
_ENCODED_CATEGORICALS = {"environment", "cloud_service_type", "workflow_criticality"}


# --------------------------------------------------------------------------- #
# Impact-text helpers
# --------------------------------------------------------------------------- #
def _phrase(feature: str) -> str:
    return FEATURE_PHRASES.get(feature, feature.replace("_", " "))


def _numeric_direction(feature: str, value: float) -> str:
    """Return 'high', 'low', or 'typical' relative to the healthy reference."""
    ref = HEALTHY_REFERENCE.get(feature)
    if ref is None or ref == 0:
        # No reference (or zero baseline): treat any positive value as high.
        return "high" if value > 0 else "typical"
    ratio = value / ref
    if ratio > 1 + _TYPICAL_BAND:
        return "high"
    if ratio < 1 - _TYPICAL_BAND:
        return "low"
    return "typical"


def _impact_text(feature: str, value: float) -> str:
    """Build a readable contribution sentence for one feature."""
    phrase = _phrase(feature)

    if feature in _BOOLEAN_RISKY_STATE:
        if feature == "public_exposure":
            state = "enabled" if value >= 0.5 else "disabled"
            tail = (
                "expanding the attack surface"
                if value >= 0.5
                else "limiting the attack surface"
            )
            return f"{phrase} is {state}, {tail}."
        # monitoring_enabled
        if value >= 0.5:
            return f"{phrase} is active, providing normal observability."
        return f"{phrase} is missing, reducing observability into this workload."

    if feature in _ENCODED_CATEGORICALS:
        return (
            f"{phrase} (encoded {value:.0f}) shapes the expected operating "
            "profile for this workload."
        )

    # Numeric features.
    direction = _numeric_direction(feature, value)
    if direction == "high":
        return f"{phrase} is unusually high ({value:,.1f}), driving the anomaly score up."
    if direction == "low":
        return f"{phrase} is unusually low ({value:,.1f}), an atypical operating pattern."
    return f"{phrase} is within the typical range ({value:,.1f})."


# --------------------------------------------------------------------------- #
# SHAP path
# --------------------------------------------------------------------------- #
def _shap_explanation(
    feature_names: list[str],
    feature_values: list[float],
    shap_values: list[float],
) -> XAIExplanation:
    """Rank features by |shap value| (descending) and build the top factors."""
    ranked = sorted(
        zip(feature_names, feature_values, shap_values),
        key=lambda triple: abs(triple[2]),
        reverse=True,
    )
    top = ranked[: max(MIN_FACTORS, min(TOP_N, len(ranked)))]
    factors = [
        XAIFactor(feature=name, value=float(value), impact=_impact_text(name, value))
        for name, value, _shap in top
    ]
    return XAIExplanation(method=SHAP_METHOD, top_contributing_factors=factors)


def _compute_shap_values(model: Any, feature_vector: list[float]) -> list[float]:
    """Run TreeExplainer on the Isolation Forest for one observation.

    Returns a flat list of 17 SHAP values aligned with ``FEATURE_COLUMNS``.
    Raises on any failure so the caller can fall back.
    """
    import numpy as np
    import shap

    explainer = shap.TreeExplainer(model)
    x = np.asarray([feature_vector], dtype=float)
    raw = explainer.shap_values(x, check_additivity=False)
    arr = np.asarray(raw, dtype=float)
    # Normalize possible shapes -> a single 17-length vector.
    arr = np.reshape(arr, (-1,)) if arr.ndim == 1 else arr
    if arr.ndim > 1:
        arr = arr[0]
    values = np.ravel(arr).astype(float).tolist()
    if len(values) != len(feature_vector):
        raise ValueError(
            f"SHAP returned {len(values)} values for "
            f"{len(feature_vector)} features"
        )
    return values


# --------------------------------------------------------------------------- #
# Rule-based fallback
# --------------------------------------------------------------------------- #
def _deviation(feature: str, value: float) -> float:
    """Normalized deviation-from-healthy used to rank fallback factors."""
    if feature in _BOOLEAN_RISKY_STATE:
        # 1.0 when the feature is in its risky state, else 0.0.
        return 1.0 if abs(value - _BOOLEAN_RISKY_STATE[feature]) < 0.5 else 0.0
    ref = HEALTHY_REFERENCE.get(feature)
    if ref is None:
        # Encoded categoricals carry no healthy reference -> neutral weight.
        return 0.0
    if ref == 0:
        return abs(value)
    return abs(value - ref) / ref


def _fallback_explanation(
    feature_names: list[str], feature_values: list[float]
) -> XAIExplanation:
    """Rank by normalized deviation from the healthy reference profile."""
    ranked = sorted(
        zip(feature_names, feature_values),
        key=lambda pair: _deviation(pair[0], pair[1]),
        reverse=True,
    )
    top = ranked[: max(MIN_FACTORS, min(TOP_N, len(ranked)))]
    factors = [
        XAIFactor(feature=name, value=float(value), impact=_impact_text(name, value))
        for name, value in top
    ]
    return XAIExplanation(method=FALLBACK_METHOD, top_contributing_factors=factors)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def explain(
    telemetry: TelemetrySnapshot,
    workload: Workload | None = None,
    detector: IsolationForestDetector | None = None,
) -> XAIExplanation:
    """Produce an ``XAIExplanation`` for a single telemetry observation.

    Uses ``shap.TreeExplainer`` on the shared Isolation Forest when both the
    model and the ``shap`` package are available; otherwise degrades to the
    rule-based feature-contribution fallback. Either way a valid
    ``XAIExplanation`` with 3-5 ranked factors is returned.
    """
    det = detector if detector is not None else get_detector()
    feature_names = det.feature_columns if det.is_available else list(FEATURE_COLUMNS)
    feature_values = build_feature_vector(telemetry, workload)

    if det.is_available and det.model is not None:
        try:
            shap_values = _compute_shap_values(det.model, feature_values)
            return _shap_explanation(feature_names, feature_values, shap_values)
        except Exception:  # noqa: BLE001 - any SHAP failure -> rule-based fallback
            logger.exception(
                "SHAP explanation failed; using rule-based feature "
                "contribution fallback."
            )

    return _fallback_explanation(list(FEATURE_COLUMNS), feature_values)


def explain_snapshot(
    telemetry: TelemetrySnapshot, workload: Workload | None = None
) -> XAIExplanation:
    """Convenience wrapper that explains via the shared cached detector."""
    return explain(telemetry, workload)
