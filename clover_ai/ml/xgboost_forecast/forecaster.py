"""XGBoost forecast inference + optimization impact (ARCHITECTURE.md §8.10-§8.12).

forecast()            -> baseline 30-day cost/energy/carbon (forecast_model_result)
optimization_impact() -> before/after/savings using a recommendation's factors

Fallback (§8.13): if model artifacts are missing, a deterministic 24h x 30
forecast is used and model_name is set to "deterministic_forecast_fallback",
keeping the exact same output schema.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from ml.common import paths
from ml.common.features import XGB_FEATURES, to_feature_row


@lru_cache(maxsize=1)
def _models():
    import joblib
    return (
        joblib.load(paths.XGB_COST_MODEL),
        joblib.load(paths.XGB_ENERGY_MODEL),
        joblib.load(paths.XGB_CARBON_MODEL),
    )


def _deterministic(t: dict) -> dict:
    return {
        "model_name": "deterministic_forecast_fallback",
        "predicted_cost_30d": round(float(t.get("cost_24h", 0)) * 30.0, 2),
        "predicted_energy_kwh_30d": round(float(t.get("energy_kwh_24h", 0)) * 30.0, 2),
        "predicted_carbon_kgco2e_30d": round(float(t.get("carbon_kgco2e_24h", 0)) * 30.0, 2),
    }


def forecast(t: dict) -> dict:
    """Return forecast_model_result (§8.12).

    Two layers of fallback to the deterministic ``current_24h x 30`` estimate
    (``model_name == "deterministic_forecast_fallback"``):

    1. Missing/broken artifacts raise inside ``_models()`` / ``predict`` and are
       caught (§8.13).
    2. A *defensive non-negative guard*: an XGBoost regressor fed
       out-of-distribution telemetry (or a cross-version model artifact) can
       emit negative or non-finite predictions, which are nonsensical for
       cost/energy/carbon and break optimization-impact arithmetic
       (savings = before - after must stay >= 0 since factors <= 1). If ANY of
       the three predictions is negative or non-finite we fall back as a whole
       so the three values stay mutually consistent.
    """
    try:
        cost_m, energy_m, carbon_m = _models()
        row = np.array([to_feature_row(t, XGB_FEATURES)], dtype=float)
        cost = float(cost_m.predict(row)[0])
        energy = float(energy_m.predict(row)[0])
        carbon = float(carbon_m.predict(row)[0])
        preds = (cost, energy, carbon)
        # Defensive guard: reject negative or non-finite predictions and fall
        # back to the deterministic estimate to keep forecasts non-negative.
        if not all(np.isfinite(p) for p in preds) or any(p < 0 for p in preds):
            return _deterministic(t)
        return {
            "model_name": "XGBoost Regressor",
            "predicted_cost_30d": round(cost, 2),
            "predicted_energy_kwh_30d": round(energy, 2),
            "predicted_carbon_kgco2e_30d": round(carbon, 2),
        }
    except Exception:  # noqa: BLE001 - §8.13 fallback
        return _deterministic(t)


def optimization_impact(t: dict, factors: dict) -> tuple[dict, dict]:
    """Compute before/after/savings (§8.10-§8.12).

    factors: {"cost": f, "energy": f, "carbon": f} where 1.0 = no change.
    Returns (forecast_model_result, optimization_impact_forecast).
    """
    fc = forecast(t)
    cost0 = fc["predicted_cost_30d"]
    energy0 = fc["predicted_energy_kwh_30d"]
    carbon0 = fc["predicted_carbon_kgco2e_30d"]

    cf = float(factors.get("cost", 1.0))
    ef = float(factors.get("energy", 1.0))
    kf = float(factors.get("carbon", 1.0))

    after = {
        "cost_30d": round(cost0 * cf, 2),
        "energy_30d_kwh": round(energy0 * ef, 2),
        "carbon_30d_kgco2e": round(carbon0 * kf, 2),
    }
    before = {
        "cost_30d": cost0,
        "energy_30d_kwh": energy0,
        "carbon_30d_kgco2e": carbon0,
    }
    savings = {
        "cost_30d": round(cost0 - after["cost_30d"], 2),
        "energy_30d_kwh": round(energy0 - after["energy_30d_kwh"], 2),
        "carbon_30d_kgco2e": round(carbon0 - after["carbon_30d_kgco2e"], 2),
    }
    impact = {
        "forecast_without_action": before,
        "forecast_after_action": after,
        "projected_savings": savings,
    }
    return fc, impact


__all__ = ["forecast", "optimization_impact"]
