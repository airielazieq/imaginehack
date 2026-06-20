"""Train (and freeze) all models in one shot.

  1. Isolation Forest  (anomaly detection, §5.5.1, frozen per §8.14)
  2. XGBoost x3         (30-day cost / energy / carbon forecast, §8.7)

Prereq: the historical dataset must exist. If missing, generate it first:
    python mock-data-generator/generate_historical.py

Run:
    python -m ml.train_all
"""
from __future__ import annotations

from ml.common import paths
from ml.isolation_forest import train as if_train
from ml.xgboost_forecast import train as xgb_train


def main() -> None:
    if not paths.HISTORICAL_CSV.exists():
        raise SystemExit(
            "Historical dataset missing. Run:\n"
            "  python mock-data-generator/generate_historical.py"
        )
    print("[1/2] Isolation Forest ...")
    if_train.main()
    print("\n[2/2] XGBoost forecast models ...")
    xgb_train.main()
    print("\nAll models trained and saved to", paths.ARTIFACTS_DIR)


if __name__ == "__main__":
    main()
