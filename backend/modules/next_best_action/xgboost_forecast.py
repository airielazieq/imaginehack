"""XGBoost 30-day cost / energy / carbon forecaster (Module 2, task 4.2).

Given a :class:`TelemetrySnapshot` (and optional :class:`Workload` context),
this module produces the baseline 30-day forecast a Recommendation is built on
(Requirement 6.1):

    * ``predicted_cost_30d``          (USD)
    * ``predicted_energy_kwh_30d``    (kWh)
    * ``predicted_carbon_kgco2e_30d`` (kgCO2e)

It loads the three :class:`xgboost.XGBRegressor` models trained by
``backend/ml/train_xgboost.py`` and reuses the **exact same 17-feature
contract** as the Isolation Forest (``FEATURE_COLUMNS`` /
``build_feature_vector`` imported from
``modules.detection_insight.isolation_forest``) so the feature vector built at
inference matches the training distribution.

Graceful degradation (Requirement 6.3): if the model bundle is missing or
unloadable, or if inference raises, the forecaster falls back to a deterministic
linear extrapolation of the current 24h telemetry over 30 days
(``current_24h x 30``) and labels the result
``model_name = "deterministic_forecast_fallback"``.

The structured output is a :class:`ForecastModelResult` (the same schema the
Recommendation carries), which downstream feeds the optimization-impact
calculator (task 4.3).
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.modules.detection_insight.isolation_forest import (
    FEATURE_COLUMNS,
    MODEL_DIR,
    build_feature_vector,
)
from backend.schemas.recommendation import ForecastModelResult
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Artifact location, target order, and result naming
# --------------------------------------------------------------------------- #
MODEL_PATH: Path = MODEL_DIR / "xgboost_forecast.joblib"

#: Forecast targets in the order the training bundle stores them.
TARGET_COLUMNS: list[str] = ["cost_30d", "energy_kwh_30d", "carbon_kgco2e_30d"]

#: Number of days the 24h telemetry is extrapolated over.
FORECAST_HORIZON_DAYS = 30

MODEL_NAME = "XGBoost Regressor"
FALLBACK_MODEL_NAME = "deterministic_forecast_fallback"

# Bundle metadata keys (what train_xgboost.py serializes).
BUNDLE_MODELS_KEY = "models"
BUNDLE_FEATURES_KEY = "feature_columns"
BUNDLE_TARGETS_KEY = "targets"


def _non_negative(value: float) -> float:
    """Clamp a forecast value at 0 (a 30-day forecast can never be negative)."""
    return value if value > 0.0 else 0.0


class XGBoostForecaster:
    """Loads the 3 trained XGBoost regressors and forecasts 30-day impact.

    The forecaster degrades gracefully: when the model bundle is unavailable or
    inference fails, it returns a deterministic ``current_24h x 30`` forecast
    rather than raising, so the NBA pipeline always produces a Recommendation.
    """

    def __init__(self, model_path: Path | str = MODEL_PATH) -> None:
        self.model_path = Path(model_path)
        self._bundle: dict[str, Any] | None = None
        self._load()

    # -- loading ---------------------------------------------------------- #
    def _load(self) -> None:
        """Attempt to load the serialized model bundle; tolerate failure."""
        if not self.model_path.exists():
            logger.warning(
                "XGBoost forecast model not found at %s; forecasting will use "
                "the deterministic linear-extrapolation fallback.",
                self.model_path,
            )
            self._bundle = None
            return
        try:
            import joblib  # imported lazily so the module loads without ML deps

            bundle = joblib.load(self.model_path)
            if not (
                isinstance(bundle, dict)
                and isinstance(bundle.get(BUNDLE_MODELS_KEY), dict)
                and all(t in bundle[BUNDLE_MODELS_KEY] for t in TARGET_COLUMNS)
            ):
                raise ValueError(
                    "XGBoost bundle missing one or more target models "
                    f"{TARGET_COLUMNS}"
                )
            self._bundle = bundle
            logger.info("Loaded XGBoost forecast models from %s", self.model_path)
        except Exception:  # noqa: BLE001 - any load failure -> fallback
            logger.exception(
                "Failed to load XGBoost forecast models from %s; falling back "
                "to deterministic forecasting.",
                self.model_path,
            )
            self._bundle = None

    def reload(self) -> None:
        """Re-read the model artifact from disk (e.g. after retraining)."""
        self._load()

    # -- introspection ---------------------------------------------------- #
    @property
    def is_available(self) -> bool:
        return self._bundle is not None

    @property
    def feature_columns(self) -> list[str]:
        """Stable feature order the models were trained on."""
        if self._bundle:
            return list(self._bundle.get(BUNDLE_FEATURES_KEY, FEATURE_COLUMNS))
        return list(FEATURE_COLUMNS)

    # -- forecasting ------------------------------------------------------ #
    def forecast(
        self,
        telemetry: TelemetrySnapshot,
        workload: Workload | None = None,
    ) -> ForecastModelResult:
        """Produce a 30-day cost/energy/carbon forecast for one snapshot.

        Returns a :class:`ForecastModelResult`. When the model is unavailable or
        inference fails, returns the deterministic ``current_24h x 30`` fallback
        with ``model_name="deterministic_forecast_fallback"`` (Requirement 6.3).
        Every predicted value is non-negative (Requirement 6.4).
        """
        if not self.is_available:
            return self._fallback_forecast(telemetry)

        try:
            import numpy as np

            features = build_feature_vector(telemetry, workload)
            x = np.asarray([features], dtype=float)
            models = self._bundle[BUNDLE_MODELS_KEY]
            predictions = {
                target: _non_negative(float(models[target].predict(x)[0]))
                for target in TARGET_COLUMNS
            }
            return ForecastModelResult(
                model_name=MODEL_NAME,
                predicted_cost_30d=predictions["cost_30d"],
                predicted_energy_kwh_30d=predictions["energy_kwh_30d"],
                predicted_carbon_kgco2e_30d=predictions["carbon_kgco2e_30d"],
            )
        except Exception:  # noqa: BLE001 - any inference failure -> fallback
            logger.exception(
                "XGBoost forecasting failed; returning deterministic fallback."
            )
            return self._fallback_forecast(telemetry)

    @staticmethod
    def _fallback_forecast(telemetry: TelemetrySnapshot) -> ForecastModelResult:
        """Deterministic linear extrapolation: ``current_24h x 30`` per dimension."""
        return ForecastModelResult(
            model_name=FALLBACK_MODEL_NAME,
            predicted_cost_30d=_non_negative(
                float(telemetry.cost_24h) * FORECAST_HORIZON_DAYS
            ),
            predicted_energy_kwh_30d=_non_negative(
                float(telemetry.energy_kwh_24h) * FORECAST_HORIZON_DAYS
            ),
            predicted_carbon_kgco2e_30d=_non_negative(
                float(telemetry.carbon_kgco2e_24h) * FORECAST_HORIZON_DAYS
            ),
        )


# --------------------------------------------------------------------------- #
# Module-level singleton (load the models once and reuse across requests)
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def get_forecaster() -> XGBoostForecaster:
    """Return a process-wide cached forecaster instance."""
    return XGBoostForecaster()


def forecast_snapshot(
    telemetry: TelemetrySnapshot, workload: Workload | None = None
) -> ForecastModelResult:
    """Convenience wrapper that forecasts via the shared cached forecaster."""
    return get_forecaster().forecast(telemetry, workload)
