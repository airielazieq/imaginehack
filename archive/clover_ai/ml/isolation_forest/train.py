"""Train and freeze the Isolation Forest anomaly detector (ARCHITECTURE.md §5.5.1, §8.14).

Trained ONCE on the healthy-variant historical dataset, then frozen for the demo:
the same telemetry always yields the same anomaly score. A StandardScaler is fit
on the same data and persisted so live inference scales identically.

Run:  python -m ml.isolation_forest.train
"""
from __future__ import annotations

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from ml.common import paths
from ml.common.features import ISO_FOREST_FEATURES

RANDOM_STATE = 42
# Healthy training data has little contamination by construction; keep it small.
CONTAMINATION = 0.02


def main() -> None:
    df = pd.read_csv(paths.HISTORICAL_CSV)
    X = df[ISO_FOREST_FEATURES].astype(float)

    # Fit on raw arrays (no column names) so live inference on numpy arrays
    # does not emit sklearn feature-name warnings.
    scaler = StandardScaler().fit(X.values)
    Xs = scaler.transform(X.values)

    model = IsolationForest(
        n_estimators=200,
        contamination=CONTAMINATION,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    ).fit(Xs)

    joblib.dump(model, paths.ISO_FOREST_MODEL)
    joblib.dump(
        {"features": ISO_FOREST_FEATURES, "scaler": scaler},
        paths.FEATURE_META,
    )
    print(f"Trained Isolation Forest on {len(df)} rows ({len(ISO_FOREST_FEATURES)} features).")
    print(f"Saved model    -> {paths.ISO_FOREST_MODEL}")
    print(f"Saved features -> {paths.FEATURE_META}")


if __name__ == "__main__":
    main()
