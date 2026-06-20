"""Train 3 XGBoost Regressors for 30-day cost / energy / carbon (ARCHITECTURE.md §8.7).

One model per target (simplest implementation, §8.7). Trained on the same
synthetic historical dataset used by Isolation Forest, with §8.9-derived targets.

Run:  python -m ml.xgboost_forecast.train
"""
from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from ml.common import paths
from ml.common.features import XGB_FEATURES

RANDOM_STATE = 42
TARGET_MODELS = {
    "target_cost_30d": paths.XGB_COST_MODEL,
    "target_energy_kwh_30d": paths.XGB_ENERGY_MODEL,
    "target_carbon_kgco2e_30d": paths.XGB_CARBON_MODEL,
}


def main() -> None:
    df = pd.read_csv(paths.HISTORICAL_CSV)
    X = df[XGB_FEATURES].astype(float).values

    for target, out_path in TARGET_MODELS.items():
        y = df[target].astype(float).values
        model = XGBRegressor(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=RANDOM_STATE,
            n_jobs=-1,
        )
        model.fit(X, y)
        pred = model.predict(X)
        mape = float(np.mean(np.abs((y - pred) / np.where(y == 0, 1, y))) * 100)
        joblib.dump(model, out_path)
        print(f"{target}: trained (train MAPE ~{mape:.1f}%) -> {out_path.name}")

    print(f"Saved 3 forecast models to {paths.ARTIFACTS_DIR}")


if __name__ == "__main__":
    main()
