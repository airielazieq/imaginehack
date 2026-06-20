"""Repo-relative path resolution. Keeps every module agnostic of the cwd."""
from pathlib import Path

# .../clover/ml/common/paths.py -> repo root is two parents up from ml/
REPO_ROOT = Path(__file__).resolve().parents[2]

MOCK_DATA_DIR = REPO_ROOT / "mock-data-generator" / "data"
ML_DIR = REPO_ROOT / "ml"
ARTIFACTS_DIR = ML_DIR / "artifacts"
RULES_DIR = REPO_ROOT / "rules"

# Static data deliverables
SAMPLE_WORKLOADS = MOCK_DATA_DIR / "sample_workloads.json"
HEALTHY_BASELINE = MOCK_DATA_DIR / "healthy_telemetry_baseline.json"
SCENARIO_PAYLOADS = MOCK_DATA_DIR / "scenario_payloads.json"
HISTORICAL_CSV = MOCK_DATA_DIR / "historical_telemetry_training_data.csv"

# Rules config
DETECTION_RULES = RULES_DIR / "detection_rules.json"
RECOMMENDATION_RULES = RULES_DIR / "recommendation_rules.json"

# Model artifacts
ISO_FOREST_MODEL = ARTIFACTS_DIR / "isolation_forest.joblib"
XGB_COST_MODEL = ARTIFACTS_DIR / "xgb_cost_30d.joblib"
XGB_ENERGY_MODEL = ARTIFACTS_DIR / "xgb_energy_30d.joblib"
XGB_CARBON_MODEL = ARTIFACTS_DIR / "xgb_carbon_30d.joblib"
FEATURE_META = ARTIFACTS_DIR / "feature_meta.joblib"

ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
