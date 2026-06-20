"""SHAP / SHAP-style feature-contribution explanations (ARCHITECTURE.md §5.6.1, §8.5).

Answers "which telemetry features made this workload look abnormal?" — framed as
contribution, never causal proof. Primary method is a deterministic standardized-
deviation contribution computed against the frozen scaler's learned normal
(mean/std). This is stable, fast, and demo-safe. If real SHAP is preferred it can
be swapped in behind the same interface; the fallback path sets method to
"rule-based feature contribution fallback" per §8.13.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from ml.common import paths
from ml.common.features import to_feature_row

# Human-readable, non-causal impact phrasing per feature + direction.
_HIGH = "high"
_LOW = "low"
_IMPACT = {
    "cpu_usage_percent": {
        _LOW: "Low CPU usage contributed to an idle/over-provisioned pattern",
        _HIGH: "Elevated CPU usage contributed to the abnormal load pattern",
    },
    "memory_usage_percent": {
        _LOW: "Low memory usage relative to allocation suggests over-provisioning",
        _HIGH: "High memory usage contributed to the abnormal pattern",
    },
    "runtime_hours_24h": {
        _HIGH: "Continuous runtime increased the waste signal",
        _LOW: "Unusually short runtime relative to baseline",
    },
    "cost_24h": {
        _HIGH: "Higher-than-baseline daily cost increased issue impact",
        _LOW: "Lower-than-baseline daily cost",
    },
    "cost_30d_forecast": {
        _HIGH: "High projected 30-day cost increased issue severity",
        _LOW: "Lower projected cost",
    },
    "energy_kwh_24h": {
        _HIGH: "Elevated energy consumption increased the sustainability impact",
        _LOW: "Lower energy consumption",
    },
    "carbon_kgco2e_24h": {
        _HIGH: "Elevated carbon emissions increased the sustainability impact",
        _LOW: "Lower carbon emissions",
    },
    "carbon_intensity_gco2_per_kwh": {
        _HIGH: "Higher grid carbon intensity amplified emissions impact",
        _LOW: "Lower grid carbon intensity",
    },
    "error_rate_percent": {
        _HIGH: "Elevated error rate contributed to a reliability concern",
        _LOW: "Low error rate",
    },
    "latency_ms": {
        _HIGH: "Higher latency contributed to a performance concern",
        _LOW: "Low latency",
    },
    "public_exposure_encoded": {
        _HIGH: "Workload is publicly exposed, raising security risk",
        _LOW: "Workload is not publicly exposed",
    },
    "public_storage_encoded": {
        _HIGH: "Storage is publicly accessible, raising security risk",
        _LOW: "Storage is not publicly accessible",
    },
    "monitoring_enabled_encoded": {
        _LOW: "Monitoring is disabled, reducing observability",
        _HIGH: "Monitoring is enabled",
    },
    "vulnerability_severity_encoded": {
        _HIGH: "High vulnerability severity increased security risk",
        _LOW: "Low/no known vulnerability",
    },
    "environment_encoded": {
        _LOW: "Non-production environment is likely safer to optimize",
        _HIGH: "Production environment raises the operational stakes",
    },
}


@lru_cache(maxsize=1)
def _scaler_meta():
    import joblib
    meta = joblib.load(paths.FEATURE_META)
    scaler = meta["scaler"]
    return meta["features"], scaler.mean_, scaler.scale_


def _impact_text(feature: str, direction: str) -> str:
    entry = _IMPACT.get(feature)
    if entry and direction in entry:
        return entry[direction]
    verb = "above" if direction == _HIGH else "below"
    return f"{feature} is notably {verb} the normal baseline"


def explain(telemetry: dict, top_k: int = 4) -> dict:
    """Return a SHAP-style explanation dict (§9.2 xai_explanation shape)."""
    try:
        features, mean, scale = _scaler_meta()
        row = np.array(to_feature_row(telemetry, features), dtype=float)
        scale_safe = np.where(scale == 0, 1.0, scale)
        z = (row - mean) / scale_safe  # standardized deviation from normal
        order = np.argsort(-np.abs(z))[:top_k]

        factors = []
        for i in order:
            feat = features[i]
            direction = _HIGH if z[i] >= 0 else _LOW
            raw_value = telemetry.get(feat.replace("_encoded", ""), telemetry.get(feat))
            factors.append({
                "feature": feat,
                "value": raw_value,
                "contribution": round(float(z[i]), 3),
                "impact": _impact_text(feat, direction),
            })
        return {
            "method": "SHAP-style feature contribution",
            "top_contributing_factors": factors,
        }
    except Exception as exc:  # noqa: BLE001 - §8.13 fallback
        return {
            "method": "rule-based feature contribution fallback",
            "top_contributing_factors": [],
            "fallback_reason": str(exc),
        }


__all__ = ["explain"]
