"""Train the XGBoost 30-day forecasters (task 4.2).

Reads ``backend/mock_data/training_data.csv`` and fits **three** independent
:class:`xgboost.XGBRegressor` models - one per forecast dimension:

    * ``cost_30d``            (USD)
    * ``energy_kwh_30d``      (kWh)
    * ``carbon_kgco2e_30d``   (kgCO2e)

All three models share the canonical **17-feature contract** used by the
Isolation Forest (imported from
``modules.detection_insight.isolation_forest`` so there is a single source of
truth for column order + categorical encodings). The fitted models plus the
feature-order metadata are serialized as one joblib bundle to
``backend/ml/models/xgboost_forecast.joblib``:

    {
        "models": {
            "cost_30d": <XGBRegressor>,
            "energy_kwh_30d": <XGBRegressor>,
            "carbon_kgco2e_30d": <XGBRegressor>,
        },
        "feature_columns": [... 17 names in order ...],
        "targets": ["cost_30d", "energy_kwh_30d", "carbon_kgco2e_30d"],
        "n_training_rows": <int>,
        "xgboost_version": "<x.y.z>",
    }

Run:
    backend/.venv/Scripts/python.exe -m backend.ml.train_xgboost
or:
    backend/.venv/Scripts/python.exe backend/ml/train_xgboost.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a bare script by ensuring the repo root (the ``backend``
# package parent) is importable.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import joblib  # noqa: E402
import pandas as pd  # noqa: E402
import xgboost  # noqa: E402
from xgboost import XGBRegressor  # noqa: E402

from backend.modules.detection_insight.isolation_forest import (  # noqa: E402
    FEATURE_COLUMNS,
    MODEL_DIR,
)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
#: The three regression targets present in training_data.csv.
TARGET_COLUMNS: list[str] = ["cost_30d", "energy_kwh_30d", "carbon_kgco2e_30d"]

RANDOM_SEED = 42
N_ESTIMATORS = 300
MAX_DEPTH = 4
LEARNING_RATE = 0.08

#: Serialized model bundle location (sibling of isolation_forest.joblib).
MODEL_PATH: Path = MODEL_DIR / "xgboost_forecast.joblib"

_TRAINING_CSV = (
    Path(__file__).resolve().parents[1] / "mock_data" / "training_data.csv"
)


def load_training_frame(csv_path: Path = _TRAINING_CSV) -> pd.DataFrame:
    """Load the training CSV, validating feature + target columns are present."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Training data not found at {csv_path}. Generate it first via "
            "backend/mock_data/generate_training_data.py."
        )
    df = pd.read_csv(csv_path)
    missing_features = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing_features:
        raise ValueError(
            f"Training data is missing required feature columns: {missing_features}"
        )
    missing_targets = [c for c in TARGET_COLUMNS if c not in df.columns]
    if missing_targets:
        raise ValueError(
            f"Training data is missing required target columns: {missing_targets}"
        )
    return df


def _make_regressor() -> XGBRegressor:
    """Construct an XGBRegressor with reproducible hyper-parameters."""
    return XGBRegressor(
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        learning_rate=LEARNING_RATE,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="reg:squarederror",
        random_state=RANDOM_SEED,
        n_jobs=1,
    )


def train_models(df: pd.DataFrame) -> dict[str, XGBRegressor]:
    """Fit one XGBRegressor per target on the 17 canonical features."""
    x = df[FEATURE_COLUMNS].astype(float).values
    models: dict[str, XGBRegressor] = {}
    for target in TARGET_COLUMNS:
        y = df[target].astype(float).values
        model = _make_regressor()
        model.fit(x, y)
        models[target] = model
    return models


def save_models(
    models: dict[str, XGBRegressor],
    n_rows: int,
    model_path: Path = MODEL_PATH,
) -> Path:
    """Serialize the 3 models + feature-order metadata bundle via joblib."""
    model_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "models": models,
        "feature_columns": list(FEATURE_COLUMNS),
        "targets": list(TARGET_COLUMNS),
        "n_training_rows": n_rows,
        "xgboost_version": xgboost.__version__,
    }
    joblib.dump(bundle, model_path)
    return model_path


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    df = load_training_frame()
    n_rows = len(df)

    models = train_models(df)
    path = save_models(models, n_rows)

    # Report a quick in-sample fit summary per target (R^2) for sanity.
    x = df[FEATURE_COLUMNS].astype(float).values
    print(
        f"[done] trained {len(models)} XGBRegressor models on "
        f"{n_rows} rows x {len(FEATURE_COLUMNS)} features"
    )
    for target in TARGET_COLUMNS:
        r2 = models[target].score(x, df[target].astype(float).values)
        print(f"[done]   {target}: in-sample R^2 = {r2:.4f}")
    print(f"[done] saved model bundle to {path}")


if __name__ == "__main__":
    main()
