"""Train the Isolation Forest anomaly detector (task 3.2).

Reads ``backend/mock_data/training_data.csv``, fits a scikit-learn
``IsolationForest(contamination=0.1)`` on the canonical 17-feature vector, and
serializes a metadata bundle to ``backend/ml/models/isolation_forest.joblib``
via joblib.

The bundle is a dict so the runtime detector (and the SHAP explainer in task
3.3) can recover the exact feature order the model was trained on:

    {
        "model": <fitted IsolationForest>,
        "feature_columns": [... 17 names in order ...],
        "contamination": 0.1,
        "n_training_rows": <int>,
        "sklearn_version": "<x.y.z>",
    }

The feature contract (column order + categorical encodings) is imported from
``modules.detection_insight.isolation_forest`` so there is a single source of
truth shared between training and inference.

Run:
    backend/.venv/Scripts/python.exe -m backend.ml.train_isolation_forest
or:
    backend/.venv/Scripts/python.exe backend/ml/train_isolation_forest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a bare script (python backend/ml/train_isolation_forest.py)
# by ensuring the repo root is importable as the ``backend`` package parent.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import joblib  # noqa: E402
import pandas as pd  # noqa: E402
import sklearn  # noqa: E402
from sklearn.ensemble import IsolationForest  # noqa: E402

from backend.modules.detection_insight.isolation_forest import (  # noqa: E402
    FEATURE_COLUMNS,
    MODEL_DIR,
    MODEL_PATH,
)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
CONTAMINATION = 0.1
RANDOM_SEED = 42
N_ESTIMATORS = 200

_TRAINING_CSV = (
    Path(__file__).resolve().parents[1] / "mock_data" / "training_data.csv"
)


def load_training_features(csv_path: Path = _TRAINING_CSV) -> pd.DataFrame:
    """Load the 17 feature columns from the training CSV in canonical order."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Training data not found at {csv_path}. Generate it first via "
            "backend/mock_data/generate_training_data.py."
        )
    df = pd.read_csv(csv_path)
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Training data is missing required feature columns: {missing}"
        )
    # Select in canonical order so the trained model's feature axis is stable.
    return df[FEATURE_COLUMNS].astype(float)


def train(csv_path: Path = _TRAINING_CSV) -> IsolationForest:
    """Fit an IsolationForest(contamination=0.1) on the training features."""
    features = load_training_features(csv_path)
    model = IsolationForest(
        n_estimators=N_ESTIMATORS,
        contamination=CONTAMINATION,
        random_state=RANDOM_SEED,
    )
    model.fit(features.values)
    return model


def save_model(model: IsolationForest, n_rows: int, model_path: Path = MODEL_PATH) -> Path:
    """Serialize the model + feature-order metadata bundle via joblib."""
    model_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model,
        "feature_columns": list(FEATURE_COLUMNS),
        "contamination": CONTAMINATION,
        "n_training_rows": n_rows,
        "sklearn_version": sklearn.__version__,
    }
    joblib.dump(bundle, model_path)
    return model_path


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    features = load_training_features()
    n_rows = len(features)

    model = IsolationForest(
        n_estimators=N_ESTIMATORS,
        contamination=CONTAMINATION,
        random_state=RANDOM_SEED,
    )
    model.fit(features.values)

    path = save_model(model, n_rows)
    n_anomalies = int((model.predict(features.values) == -1).sum())
    print(
        f"[done] trained IsolationForest(contamination={CONTAMINATION}) on "
        f"{n_rows} rows x {len(FEATURE_COLUMNS)} features"
    )
    print(f"[done] flagged {n_anomalies} training rows as anomalies "
          f"(~{100 * n_anomalies / n_rows:.1f}%)")
    print(f"[done] saved model bundle to {path}")


if __name__ == "__main__":
    main()
