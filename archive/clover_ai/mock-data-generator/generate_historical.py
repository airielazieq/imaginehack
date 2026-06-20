"""Generate historical_telemetry_training_data.csv (ARCHITECTURE.md §8.9, §10.9).

Produces healthy-variant telemetry rows per workload by jittering each healthy
baseline. This dataset serves two consumers:

  * Isolation Forest — learns the "normal" baseline and is then frozen (§8.14).
    We deliberately generate only healthy variation here so scenario patches
    register as anomalies at inference time.
  * XGBoost forecast — regression targets target_{cost,energy,carbon}_30d are
    derived with the §8.9 formula (24h value x 30 x noise_factor in 0.85-1.20).

Side output: data/metric_baselines.json — per-workload trailing means used by
the rules config to compute data-derived thresholds (baseline x multiplier, §6.11).

Run:  python mock-data-generator/generate_historical.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

# Allow running as a script: make repo root importable for `ml.common`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.common import data, paths  # noqa: E402
from ml.common.features import encode_telemetry  # noqa: E402

ROWS_PER_WORKLOAD = 120          # within §10.8 (50-200/workload)
SEED = 42
RNG = np.random.default_rng(SEED)

# Fields jittered as healthy variation, with relative noise std-dev.
JITTER = {
    "cpu_usage_percent": 0.12,
    "memory_usage_percent": 0.10,
    "runtime_hours_24h": 0.08,
    "storage_gb": 0.05,
    "request_count_24h": 0.18,
    "error_rate_percent": 0.25,
    "latency_ms": 0.12,
    "cost_per_hour": 0.06,
    "energy_kwh_24h": 0.10,
    "carbon_intensity_gco2_per_kwh": 0.04,
}

# Telemetry columns written to CSV (raw + encoded + targets).
RAW_NUMERIC = [
    "cpu_usage_percent", "memory_usage_percent", "runtime_hours_24h", "storage_gb",
    "request_count_24h", "error_rate_percent", "latency_ms", "cost_per_hour",
    "cost_24h", "cost_30d_forecast", "energy_kwh_24h", "carbon_kgco2e_24h",
    "carbon_intensity_gco2_per_kwh",
]
RAW_CATEGORICAL = ["workload_id", "workload_type", "cloud_service_type",
                   "environment", "region", "workflow_criticality",
                   "vulnerability_severity"]
RAW_BOOL = ["public_exposure", "public_storage", "monitoring_enabled",
            "access_anomaly_detected"]
ENCODED = [
    "environment_encoded", "cloud_service_type_encoded", "workflow_criticality_encoded",
    "vulnerability_severity_encoded", "workload_type_encoded", "region_encoded",
    "public_exposure_encoded", "public_storage_encoded", "monitoring_enabled_encoded",
]
TARGETS = ["target_cost_30d", "target_energy_kwh_30d", "target_carbon_kgco2e_30d"]
COLUMNS = RAW_CATEGORICAL + RAW_BOOL + RAW_NUMERIC + ENCODED + TARGETS

# Metrics whose trailing mean becomes a threshold baseline (§6.11).
BASELINE_METRICS = ["cost_24h", "cost_30d_forecast", "carbon_kgco2e_24h",
                    "energy_kwh_24h", "error_rate_percent"]


def _jitter(value: float, rel_std: float) -> float:
    return float(max(0.0, value * (1.0 + RNG.normal(0.0, rel_std))))


def _row_for(base: dict) -> dict:
    r = dict(base)
    for field, std in JITTER.items():
        if field in r and isinstance(r[field], (int, float)):
            r[field] = round(_jitter(r[field], std), 3)

    # Keep cost_24h coherent with cost_per_hour x runtime.
    r["cost_24h"] = round(r["cost_per_hour"] * r["runtime_hours_24h"], 3)
    r["cost_30d_forecast"] = round(r["cost_24h"] * 30.0, 3)

    # Carbon derives from energy x intensity (kg = kWh * gCO2/kWh / 1000).
    r["carbon_kgco2e_24h"] = round(
        r["energy_kwh_24h"] * r["carbon_intensity_gco2_per_kwh"] / 1000.0, 3
    )

    # §8.9 forecast targets with independent noise factors per target.
    nf = lambda: float(RNG.uniform(0.85, 1.20))
    r["target_cost_30d"] = round(r["cost_24h"] * 30.0 * nf(), 3)
    r["target_energy_kwh_30d"] = round(r["energy_kwh_24h"] * 30.0 * nf(), 3)
    r["target_carbon_kgco2e_30d"] = round(r["carbon_kgco2e_24h"] * 30.0 * nf(), 3)
    return r


def main() -> None:
    baselines = data.load_baselines()
    all_rows: list[dict] = []
    metric_baselines: dict[str, dict] = {}

    for wid, base in baselines.items():
        rows = [_row_for(base) for _ in range(ROWS_PER_WORKLOAD)]
        for r in rows:
            all_rows.append(encode_telemetry(r))
        # Per-workload trailing mean per metric -> threshold baseline (§6.11).
        metric_baselines[wid] = {
            m: round(float(np.mean([r[m] for r in rows])), 3) for m in BASELINE_METRICS
        }

    # Write CSV.
    paths.HISTORICAL_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(paths.HISTORICAL_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in all_rows:
            w.writerow(r)

    # Write metric baselines for the rules config.
    mb_path = paths.MOCK_DATA_DIR / "metric_baselines.json"
    with open(mb_path, "w", encoding="utf-8") as f:
        json.dump({"_comment": "Per-workload trailing-mean baselines (§6.11). "
                               "thresholds = baseline x multiplier (see rules/*.json).",
                   "baselines": metric_baselines}, f, indent=2)

    print(f"Wrote {len(all_rows)} rows -> {paths.HISTORICAL_CSV}")
    print(f"Wrote metric baselines -> {mb_path}")


if __name__ == "__main__":
    main()
