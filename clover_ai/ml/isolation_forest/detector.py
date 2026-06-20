"""Isolation Forest inference (ARCHITECTURE.md §5.5.1).

Loads the frozen model + scaler and scores a single telemetry dict. If the model
artifact is missing or fails to load, falls back to rule-only operation per §5.9
(model_name = "fallback_rules_only").
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from ml.common import paths
from ml.common.features import ISO_FOREST_FEATURES, to_feature_row


@lru_cache(maxsize=1)
def _load():
    import joblib
    model = joblib.load(paths.ISO_FOREST_MODEL)
    meta = joblib.load(paths.FEATURE_META)
    return model, meta["scaler"], meta["features"]


def score(telemetry: dict) -> dict:
    """Return {model_name, anomaly_score, is_anomaly}.

    anomaly_score uses score_samples (lower = more anomalous), matching the
    negative convention in §5.5.1's example (-0.71).
    """
    try:
        model, scaler, features = _load()
        row = np.array([to_feature_row(telemetry, features)], dtype=float)
        rows = scaler.transform(row)
        raw = float(model.score_samples(rows)[0])
        is_anom = bool(model.predict(rows)[0] == -1)
        return {
            "model_name": "Isolation Forest",
            "anomaly_score": round(raw, 4),
            "is_anomaly": is_anom,
        }
    except Exception as exc:  # noqa: BLE001 - fallback is intentional (§5.9)
        return {
            "model_name": "fallback_rules_only",
            "anomaly_score": None,
            "is_anomaly": None,
            "fallback_reason": str(exc),
        }


__all__ = ["score", "ISO_FOREST_FEATURES"]
