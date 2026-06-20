"""Isolation Forest anomaly detection (task 3.2).

This module owns three responsibilities for Module 1:

1. The **canonical 17-feature contract** (order, names, and categorical
   encodings) shared with the training script and the SHAP explainer
   (task 3.3). Keeping a single source of truth here guarantees the feature
   vector built at inference time matches the one the model was trained on.
2. A **feature extractor** that turns a ``TelemetrySnapshot`` (+ optional
   ``Workload`` context) into that ordered numeric vector, applying the same
   categorical encodings the mock generator used to build ``training_data.csv``.
3. A **detector** that loads the serialized ``IsolationForest`` from
   ``backend/ml/models/`` and produces an ``MLResult`` (anomaly_score +
   is_anomaly). If the model artifact is missing or unloadable it degrades to
   a neutral fallback ``MLResult`` with ``model_name="fallback_rules_only"`` so
   the detection pipeline still runs (Requirement 2.3).

The Isolation Forest only decides *that* a workload looks unusual; the
rule classifier decides *what* the issue is (spec 04 §4-5).

Design references: design.md "Isolation Forest Configuration", spec 04 §4,
spec 09 §1/§6.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.schemas.issue import MLResult
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Canonical feature contract (must match generate_training_data.py / CSV)
# --------------------------------------------------------------------------- #
# 12 numeric telemetry features.
NUMERIC_FEATURES: list[str] = [
    "cpu_usage_percent",
    "memory_usage_percent",
    "runtime_hours_24h",
    "storage_gb",
    "request_count_24h",
    "error_rate_percent",
    "latency_ms",
    "cost_24h",
    "cost_30d_forecast",
    "energy_kwh_24h",
    "carbon_kgco2e_24h",
    "carbon_intensity_gco2_per_kwh",
]
# 5 encoded categorical features.
ENCODED_FEATURES: list[str] = [
    "environment",
    "cloud_service_type",
    "workflow_criticality",
    "public_exposure",
    "monitoring_enabled",
]
# Stable 17-feature order used for both training and inference.
FEATURE_COLUMNS: list[str] = NUMERIC_FEATURES + ENCODED_FEATURES

# Categorical encodings — identical to the mock data generator so the feature
# vector built at inference matches the training distribution.
ENV_CODES: dict[str, int] = {
    "production": 0,
    "staging": 1,
    "testing": 2,
    "development": 3,
}
SERVICE_CODES: dict[str, int] = {
    "vm": 0,
    "container": 1,
    "database": 2,
    "storage": 3,
    "serverless": 4,
    "pipeline": 5,
}
CRITICALITY_CODES: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

# Defaults applied when workload context is unavailable at inference time.
_DEFAULT_ENV_CODE = ENV_CODES["production"]
_DEFAULT_SERVICE_CODE = SERVICE_CODES["container"]
_DEFAULT_CRITICALITY_CODE = CRITICALITY_CODES["medium"]

# --------------------------------------------------------------------------- #
# Model artifact location and result naming
# --------------------------------------------------------------------------- #
MODEL_DIR: Path = Path(__file__).resolve().parents[2] / "ml" / "models"
MODEL_PATH: Path = MODEL_DIR / "isolation_forest.joblib"

MODEL_NAME = "Isolation Forest"
FALLBACK_MODEL_NAME = "fallback_rules_only"

# Bundle metadata keys (what train_isolation_forest.py serializes).
BUNDLE_MODEL_KEY = "model"
BUNDLE_FEATURES_KEY = "feature_columns"
BUNDLE_CONTAMINATION_KEY = "contamination"


# --------------------------------------------------------------------------- #
# Feature extraction
# --------------------------------------------------------------------------- #
def build_feature_vector(
    telemetry: TelemetrySnapshot,
    workload: Workload | None = None,
) -> list[float]:
    """Build the ordered 17-element feature vector for a single observation.

    Numeric telemetry features map directly; the three workload-derived
    categoricals (environment, cloud_service_type, workflow_criticality) are
    integer-encoded, and the two telemetry booleans (public_exposure,
    monitoring_enabled) become 0/1. When ``workload`` is ``None`` the
    categorical codes fall back to neutral defaults so detection still runs.

    The returned order is exactly ``FEATURE_COLUMNS``.
    """
    if workload is not None:
        env_code = ENV_CODES.get(workload.environment, _DEFAULT_ENV_CODE)
        service_code = SERVICE_CODES.get(
            workload.cloud_service_type, _DEFAULT_SERVICE_CODE
        )
        crit_code = CRITICALITY_CODES.get(
            workload.workflow_criticality, _DEFAULT_CRITICALITY_CODE
        )
    else:
        env_code = _DEFAULT_ENV_CODE
        service_code = _DEFAULT_SERVICE_CODE
        crit_code = _DEFAULT_CRITICALITY_CODE

    return [
        # numeric (12)
        float(telemetry.cpu_usage_percent),
        float(telemetry.memory_usage_percent),
        float(telemetry.runtime_hours_24h),
        float(telemetry.storage_gb),
        float(telemetry.request_count_24h),
        float(telemetry.error_rate_percent),
        float(telemetry.latency_ms),
        float(telemetry.cost_24h),
        float(telemetry.cost_30d_forecast),
        float(telemetry.energy_kwh_24h),
        float(telemetry.carbon_kgco2e_24h),
        float(telemetry.carbon_intensity_gco2_per_kwh),
        # encoded categoricals (5)
        float(env_code),
        float(service_code),
        float(crit_code),
        1.0 if telemetry.public_exposure else 0.0,
        1.0 if telemetry.monitoring_enabled else 0.0,
    ]


# --------------------------------------------------------------------------- #
# Detector
# --------------------------------------------------------------------------- #
class IsolationForestDetector:
    """Loads a trained IsolationForest and scores telemetry observations.

    The loaded estimator and the feature-vector builder are deliberately
    exposed (``model`` property, ``feature_columns`` property,
    ``build_feature_vector``) so the SHAP explainer (task 3.3) can reuse the
    exact same model and feature ordering.
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
                "Isolation Forest model not found at %s; "
                "detection will use the rules-only fallback.",
                self.model_path,
            )
            self._bundle = None
            return
        try:
            import joblib  # imported lazily so the module loads without ML deps

            bundle = joblib.load(self.model_path)
            # Accept either a bare estimator or a metadata bundle dict.
            if isinstance(bundle, dict) and BUNDLE_MODEL_KEY in bundle:
                self._bundle = bundle
            else:
                self._bundle = {
                    BUNDLE_MODEL_KEY: bundle,
                    BUNDLE_FEATURES_KEY: FEATURE_COLUMNS,
                }
            logger.info("Loaded Isolation Forest model from %s", self.model_path)
        except Exception:  # noqa: BLE001 - any load failure -> fallback
            logger.exception(
                "Failed to load Isolation Forest model from %s; "
                "falling back to rules-only detection.",
                self.model_path,
            )
            self._bundle = None

    def reload(self) -> None:
        """Re-read the model artifact from disk (e.g. after retraining)."""
        self._load()

    # -- introspection (reused by the SHAP explainer) -------------------- #
    @property
    def is_available(self) -> bool:
        return self._bundle is not None

    @property
    def model(self) -> Any | None:
        """The underlying fitted IsolationForest, or None when unavailable."""
        return self._bundle[BUNDLE_MODEL_KEY] if self._bundle else None

    @property
    def feature_columns(self) -> list[str]:
        """Stable feature order the model was trained on."""
        if self._bundle:
            return list(self._bundle.get(BUNDLE_FEATURES_KEY, FEATURE_COLUMNS))
        return list(FEATURE_COLUMNS)

    @staticmethod
    def build_feature_vector(
        telemetry: TelemetrySnapshot, workload: Workload | None = None
    ) -> list[float]:
        """Expose the feature builder on the detector for SHAP reuse."""
        return build_feature_vector(telemetry, workload)

    # -- scoring ---------------------------------------------------------- #
    def score(
        self,
        telemetry: TelemetrySnapshot,
        workload: Workload | None = None,
    ) -> MLResult:
        """Produce an ``MLResult`` (anomaly_score + is_anomaly) for one snapshot.

        ``anomaly_score`` is oriented so that **higher means more anomalous**
        (it is the negated scikit-learn ``score_samples`` value, whose raw form
        is "lower = more abnormal"). ``is_anomaly`` is True when the model
        predicts the observation as an outlier (predict == -1).

        If the model is unavailable or scoring raises, a neutral fallback
        ``MLResult`` is returned with ``model_name="fallback_rules_only"`` so
        the rules-only path can still classify the issue (Requirement 2.3).
        """
        if not self.is_available:
            return self._fallback_result()

        try:
            import numpy as np

            features = build_feature_vector(telemetry, workload)
            x = np.asarray([features], dtype=float)
            # score_samples: the lower, the more abnormal -> negate so that
            # higher = more anomalous, which is more intuitive downstream.
            raw_score = float(self.model.score_samples(x)[0])
            anomaly_score = -raw_score
            is_anomaly = bool(int(self.model.predict(x)[0]) == -1)
            return MLResult(
                model_name=MODEL_NAME,
                anomaly_score=anomaly_score,
                is_anomaly=is_anomaly,
            )
        except Exception:  # noqa: BLE001 - any inference failure -> fallback
            logger.exception(
                "Isolation Forest scoring failed; returning rules-only fallback."
            )
            return self._fallback_result()

    @staticmethod
    def _fallback_result() -> MLResult:
        """Neutral result used when the model is unavailable/unloadable."""
        return MLResult(
            model_name=FALLBACK_MODEL_NAME,
            anomaly_score=0.0,
            is_anomaly=False,
        )


# --------------------------------------------------------------------------- #
# Module-level singleton (so the model is loaded once and reused, incl. by SHAP)
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def get_detector() -> IsolationForestDetector:
    """Return a process-wide cached detector instance."""
    return IsolationForestDetector()


def score_snapshot(
    telemetry: TelemetrySnapshot, workload: Workload | None = None
) -> MLResult:
    """Convenience wrapper that scores via the shared cached detector."""
    return get_detector().score(telemetry, workload)
