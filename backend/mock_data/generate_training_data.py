"""Generate synthetic ML training data for the Clover platform.

Produces ``backend/mock_data/training_data.csv`` containing 50-200 historical
telemetry rows per workload. The data feeds two models:

  * XGBoost 30-day forecaster (3 regressors: cost / energy / carbon)
  * Isolation Forest anomaly detector

Feature set (17 features, per design.md and spec 09):

  Numeric (12):
    cpu_usage_percent, memory_usage_percent, runtime_hours_24h, storage_gb,
    request_count_24h, error_rate_percent, latency_ms, cost_24h,
    cost_30d_forecast, energy_kwh_24h, carbon_kgco2e_24h,
    carbon_intensity_gco2_per_kwh

  Encoded categoricals (5):
    environment, cloud_service_type, workflow_criticality,
    public_exposure, monitoring_enabled

XGBoost targets (computed as ``current_24h * 30 * noise`` with
``noise in [0.85, 1.20]``, inflated for issue/waste scenarios):
    cost_30d, energy_kwh_30d, carbon_kgco2e_30d

The script is deterministic (fixed RNG seed). It reads workload definitions
from ``sample_workloads.json`` when that file exists (created by task 2.1);
otherwise it falls back to a built-in list so the script is self-contained.

Run:
    backend/.venv/Scripts/python.exe backend/mock_data/generate_training_data.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
RANDOM_SEED = 42
MIN_ROWS_PER_WORKLOAD = 50
MAX_ROWS_PER_WORKLOAD = 200

HERE = Path(__file__).resolve().parent
SAMPLE_WORKLOADS_PATH = HERE / "sample_workloads.json"
OUTPUT_CSV_PATH = HERE / "training_data.csv"

# The 17 model features in canonical order.
NUMERIC_FEATURES = [
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
# Encoded categoricals (integer codes for ML consumption).
ENCODED_FEATURES = [
    "environment",
    "cloud_service_type",
    "workflow_criticality",
    "public_exposure",
    "monitoring_enabled",
]
FEATURE_COLUMNS = NUMERIC_FEATURES + ENCODED_FEATURES
TARGET_COLUMNS = ["cost_30d", "energy_kwh_30d", "carbon_kgco2e_30d"]

# Categorical encodings (stable integer codes shared with the model layer).
ENV_CODES = {"production": 0, "staging": 1, "testing": 2, "development": 3}
SERVICE_CODES = {
    "vm": 0,
    "container": 1,
    "database": 2,
    "storage": 3,
    "serverless": 4,
    "pipeline": 5,
}
CRITICALITY_CODES = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# --------------------------------------------------------------------------- #
# Built-in fallback workloads (used only when sample_workloads.json is absent).
#
# Each entry carries the categorical attributes plus a per-workload telemetry
# "profile" (mean values) used to draw realistic rows. ``waste`` flags
# idle/over-provisioned/cost-spike workloads whose targets get inflated noise.
# --------------------------------------------------------------------------- #
def _fallback_workloads() -> list[dict]:
    return [
        {
            "workload_id": "field-app", "cloud_service_type": "container",
            "environment": "production", "workflow_criticality": "high",
            "public_exposure": True, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 55, "mem": 60, "runtime": 24, "storage": 40,
                        "requests": 120000, "error_rate": 0.6, "latency": 140,
                        "cost_per_hour": 1.2, "energy_per_hour": 0.45,
                        "carbon_intensity": 380},
        },
        {
            "workload_id": "iot-dashboard", "cloud_service_type": "serverless",
            "environment": "production", "workflow_criticality": "high",
            "public_exposure": True, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 35, "mem": 45, "runtime": 24, "storage": 15,
                        "requests": 250000, "error_rate": 0.4, "latency": 90,
                        "cost_per_hour": 0.8, "energy_per_hour": 0.3,
                        "carbon_intensity": 410},
        },
        {
            "workload_id": "bim-processor", "cloud_service_type": "vm",
            "environment": "production", "workflow_criticality": "critical",
            "public_exposure": False, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 78, "mem": 82, "runtime": 18, "storage": 320,
                        "requests": 8000, "error_rate": 1.1, "latency": 220,
                        "cost_per_hour": 3.5, "energy_per_hour": 1.6,
                        "carbon_intensity": 450},
        },
        {
            "workload_id": "doc-storage", "cloud_service_type": "storage",
            "environment": "production", "workflow_criticality": "medium",
            "public_exposure": True, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 8, "mem": 12, "runtime": 24, "storage": 1200,
                        "requests": 30000, "error_rate": 0.2, "latency": 60,
                        "cost_per_hour": 0.6, "energy_per_hour": 0.2,
                        "carbon_intensity": 400},
        },
        {
            "workload_id": "report-generator", "cloud_service_type": "pipeline",
            "environment": "staging", "workflow_criticality": "medium",
            "public_exposure": False, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 45, "mem": 50, "runtime": 6, "storage": 80,
                        "requests": 1500, "error_rate": 1.8, "latency": 300,
                        "cost_per_hour": 1.0, "energy_per_hour": 0.5,
                        "carbon_intensity": 420},
        },
        {
            "workload_id": "ci-pipeline", "cloud_service_type": "pipeline",
            "environment": "development", "workflow_criticality": "low",
            "public_exposure": False, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 40, "mem": 55, "runtime": 4, "storage": 60,
                        "requests": 900, "error_rate": 2.5, "latency": 250,
                        "cost_per_hour": 0.9, "energy_per_hour": 0.4,
                        "carbon_intensity": 390},
        },
        {
            "workload_id": "costly-vm", "cloud_service_type": "vm",
            "environment": "development", "workflow_criticality": "low",
            "public_exposure": False, "monitoring_enabled": False, "waste": True,
            "profile": {"cpu": 6, "mem": 15, "runtime": 24, "storage": 200,
                        "requests": 50, "error_rate": 0.1, "latency": 110,
                        "cost_per_hour": 4.2, "energy_per_hour": 2.0,
                        "carbon_intensity": 480},
        },
        {
            "workload_id": "site-db", "cloud_service_type": "database",
            "environment": "production", "workflow_criticality": "critical",
            "public_exposure": False, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 65, "mem": 75, "runtime": 24, "storage": 800,
                        "requests": 180000, "error_rate": 0.8, "latency": 45,
                        "cost_per_hour": 2.8, "energy_per_hour": 1.3,
                        "carbon_intensity": 430},
        },
        # Extra workloads to bring the fallback set toward ~20.
        {
            "workload_id": "safety-analytics", "cloud_service_type": "container",
            "environment": "production", "workflow_criticality": "high",
            "public_exposure": False, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 58, "mem": 62, "runtime": 24, "storage": 90,
                        "requests": 40000, "error_rate": 1.0, "latency": 130,
                        "cost_per_hour": 1.5, "energy_per_hour": 0.7,
                        "carbon_intensity": 410},
        },
        {
            "workload_id": "order-platform", "cloud_service_type": "container",
            "environment": "production", "workflow_criticality": "high",
            "public_exposure": True, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 62, "mem": 68, "runtime": 24, "storage": 110,
                        "requests": 300000, "error_rate": 0.7, "latency": 100,
                        "cost_per_hour": 2.0, "energy_per_hour": 0.9,
                        "carbon_intensity": 400},
        },
        {
            "workload_id": "progress-tracker", "cloud_service_type": "serverless",
            "environment": "staging", "workflow_criticality": "medium",
            "public_exposure": False, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 30, "mem": 38, "runtime": 12, "storage": 25,
                        "requests": 60000, "error_rate": 0.9, "latency": 120,
                        "cost_per_hour": 0.7, "energy_per_hour": 0.3,
                        "carbon_intensity": 415},
        },
        {
            "workload_id": "pm-dashboard", "cloud_service_type": "container",
            "environment": "production", "workflow_criticality": "medium",
            "public_exposure": True, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 48, "mem": 54, "runtime": 24, "storage": 70,
                        "requests": 95000, "error_rate": 0.5, "latency": 110,
                        "cost_per_hour": 1.3, "energy_per_hour": 0.6,
                        "carbon_intensity": 405},
        },
        {
            "workload_id": "equipment-monitor", "cloud_service_type": "serverless",
            "environment": "production", "workflow_criticality": "high",
            "public_exposure": False, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 28, "mem": 36, "runtime": 24, "storage": 18,
                        "requests": 420000, "error_rate": 0.3, "latency": 80,
                        "cost_per_hour": 0.9, "energy_per_hour": 0.35,
                        "carbon_intensity": 400},
        },
        {
            "workload_id": "analytics-batch", "cloud_service_type": "pipeline",
            "environment": "staging", "workflow_criticality": "low",
            "public_exposure": False, "monitoring_enabled": True, "waste": True,
            "profile": {"cpu": 72, "mem": 78, "runtime": 10, "storage": 260,
                        "requests": 1200, "error_rate": 1.5, "latency": 350,
                        "cost_per_hour": 3.0, "energy_per_hour": 1.8,
                        "carbon_intensity": 520},
        },
        {
            "workload_id": "media-store", "cloud_service_type": "storage",
            "environment": "production", "workflow_criticality": "low",
            "public_exposure": True, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 5, "mem": 10, "runtime": 24, "storage": 2400,
                        "requests": 15000, "error_rate": 0.1, "latency": 70,
                        "cost_per_hour": 1.1, "energy_per_hour": 0.4,
                        "carbon_intensity": 395},
        },
        {
            "workload_id": "auth-service", "cloud_service_type": "container",
            "environment": "production", "workflow_criticality": "critical",
            "public_exposure": True, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 40, "mem": 50, "runtime": 24, "storage": 30,
                        "requests": 500000, "error_rate": 0.4, "latency": 55,
                        "cost_per_hour": 1.4, "energy_per_hour": 0.6,
                        "carbon_intensity": 400},
        },
        {
            "workload_id": "test-runner", "cloud_service_type": "vm",
            "environment": "testing", "workflow_criticality": "low",
            "public_exposure": False, "monitoring_enabled": False, "waste": True,
            "profile": {"cpu": 9, "mem": 20, "runtime": 22, "storage": 90,
                        "requests": 300, "error_rate": 0.2, "latency": 130,
                        "cost_per_hour": 2.1, "energy_per_hour": 1.0,
                        "carbon_intensity": 460},
        },
        {
            "workload_id": "notification-svc", "cloud_service_type": "serverless",
            "environment": "production", "workflow_criticality": "medium",
            "public_exposure": False, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 22, "mem": 30, "runtime": 24, "storage": 12,
                        "requests": 220000, "error_rate": 0.6, "latency": 95,
                        "cost_per_hour": 0.6, "energy_per_hour": 0.25,
                        "carbon_intensity": 405},
        },
        {
            "workload_id": "archive-db", "cloud_service_type": "database",
            "environment": "staging", "workflow_criticality": "medium",
            "public_exposure": False, "monitoring_enabled": True, "waste": False,
            "profile": {"cpu": 18, "mem": 40, "runtime": 24, "storage": 1500,
                        "requests": 5000, "error_rate": 0.3, "latency": 50,
                        "cost_per_hour": 1.6, "energy_per_hour": 0.75,
                        "carbon_intensity": 420},
        },
        {
            "workload_id": "etl-loader", "cloud_service_type": "pipeline",
            "environment": "development", "workflow_criticality": "low",
            "public_exposure": False, "monitoring_enabled": False, "waste": True,
            "profile": {"cpu": 7, "mem": 18, "runtime": 23, "storage": 140,
                        "requests": 200, "error_rate": 3.0, "latency": 400,
                        "cost_per_hour": 2.4, "energy_per_hour": 1.2,
                        "carbon_intensity": 500},
        },
    ]


# --------------------------------------------------------------------------- #
# Workload loading
# --------------------------------------------------------------------------- #
def _coerce_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if value is None:
        return default
    return bool(value)


def load_workloads() -> list[dict]:
    """Load workloads from sample_workloads.json if present, else fallback.

    The script is tolerant of the sample file format: it accepts either a bare
    list of workload objects or an object with a ``workloads`` key. Missing
    categorical attributes default to sensible values, and a synthetic
    telemetry profile is derived when the sample file lacks one.
    """
    if SAMPLE_WORKLOADS_PATH.exists():
        try:
            raw = json.loads(SAMPLE_WORKLOADS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:  # pragma: no cover
            print(f"[warn] could not read {SAMPLE_WORKLOADS_PATH.name}: {exc}; "
                  "using built-in fallback workloads.")
            return _fallback_workloads()

        items = raw["workloads"] if isinstance(raw, dict) and "workloads" in raw else raw
        if not isinstance(items, list) or not items:
            print(f"[warn] {SAMPLE_WORKLOADS_PATH.name} has no usable workloads; "
                  "using built-in fallback workloads.")
            return _fallback_workloads()

        # Index built-in profiles by id so we can enrich sample entries that
        # lack telemetry baselines.
        fallback_by_id = {w["workload_id"]: w for w in _fallback_workloads()}
        workloads: list[dict] = []
        for item in items:
            wid = item.get("workload_id") or item.get("id")
            if not wid:
                continue
            base = fallback_by_id.get(wid, {})
            profile = item.get("profile") or base.get("profile") or _default_profile()
            workloads.append({
                "workload_id": wid,
                "cloud_service_type": item.get("cloud_service_type")
                    or base.get("cloud_service_type", "container"),
                "environment": item.get("environment")
                    or base.get("environment", "production"),
                "workflow_criticality": item.get("workflow_criticality")
                    or base.get("workflow_criticality", "medium"),
                "public_exposure": _coerce_bool(
                    item.get("public_exposure", base.get("public_exposure", False))),
                "monitoring_enabled": _coerce_bool(
                    item.get("monitoring_enabled", base.get("monitoring_enabled", True)),
                    default=True),
                "waste": _coerce_bool(item.get("waste", base.get("waste", False))),
                "profile": profile,
            })
        if workloads:
            print(f"[info] loaded {len(workloads)} workloads from "
                  f"{SAMPLE_WORKLOADS_PATH.name}.")
            return workloads

    print("[info] sample_workloads.json not found; using built-in fallback "
          "workloads.")
    return _fallback_workloads()


def _default_profile() -> dict:
    return {"cpu": 40, "mem": 50, "runtime": 24, "storage": 100,
            "requests": 50000, "error_rate": 0.8, "latency": 150,
            "cost_per_hour": 1.2, "energy_per_hour": 0.5,
            "carbon_intensity": 410}


# --------------------------------------------------------------------------- #
# Row generation
# --------------------------------------------------------------------------- #
def _clip(value: float, lo: float, hi: float) -> float:
    return float(min(max(value, lo), hi))


def generate_rows(workload: dict, rng: np.random.Generator) -> list[dict]:
    """Generate 50-200 synthetic telemetry rows for one workload."""
    profile = workload["profile"]
    n_rows = int(rng.integers(MIN_ROWS_PER_WORKLOAD, MAX_ROWS_PER_WORKLOAD + 1))
    is_waste = workload["waste"]

    env_code = ENV_CODES.get(workload["environment"], 0)
    service_code = SERVICE_CODES.get(workload["cloud_service_type"], 1)
    crit_code = CRITICALITY_CODES.get(workload["workflow_criticality"], 2)
    public_code = 1 if workload["public_exposure"] else 0
    monitoring_code = 1 if workload["monitoring_enabled"] else 0

    rows: list[dict] = []
    for _ in range(n_rows):
        # Multiplicative jitter around the profile mean (+/- ~15%).
        def jit(mean: float, spread: float = 0.15) -> float:
            return mean * float(rng.normal(1.0, spread))

        cpu = _clip(jit(profile["cpu"]), 0, 100)
        mem = _clip(jit(profile["mem"]), 0, 100)
        runtime = _clip(jit(profile["runtime"], 0.10), 0, 24)
        storage = _clip(jit(profile["storage"]), 0, 1e6)
        requests = max(0, int(jit(profile["requests"], 0.25)))
        error_rate = _clip(jit(profile["error_rate"], 0.40), 0, 100)
        latency = _clip(jit(profile["latency"], 0.20), 0, 1e6)
        carbon_intensity = _clip(jit(profile["carbon_intensity"], 0.08), 0, 1e6)

        # Cost / energy / carbon derive from per-hour rates scaled by runtime
        # and a small efficiency factor tied to utilization.
        util_factor = 0.5 + (cpu / 100.0)  # 0.5 .. 1.5
        cost_24h = _clip(profile["cost_per_hour"] * runtime * util_factor
                         * float(rng.normal(1.0, 0.10)), 0, 999999.99)
        energy_kwh_24h = _clip(profile["energy_per_hour"] * runtime * util_factor
                               * float(rng.normal(1.0, 0.10)), 0, 1e6)
        carbon_kgco2e_24h = _clip(
            energy_kwh_24h * (carbon_intensity / 1000.0), 0, 1e6)

        # 30-day forecast field carried in telemetry (linear-ish extrapolation
        # with mild noise) — distinct from the XGBoost training targets.
        cost_30d_forecast = _clip(cost_24h * 30 * float(rng.uniform(0.9, 1.1)),
                                  0, 999999.99)

        # XGBoost targets: current_24h * 30 * noise; inflate for waste rows.
        noise_lo, noise_hi = (1.10, 1.45) if is_waste else (0.85, 1.20)
        cost_30d = _clip(cost_24h * 30 * float(rng.uniform(noise_lo, noise_hi)),
                         0, 1e9)
        energy_kwh_30d = _clip(
            energy_kwh_24h * 30 * float(rng.uniform(noise_lo, noise_hi)), 0, 1e9)
        carbon_kgco2e_30d = _clip(
            carbon_kgco2e_24h * 30 * float(rng.uniform(noise_lo, noise_hi)),
            0, 1e9)

        rows.append({
            "workload_id": workload["workload_id"],
            # numeric features
            "cpu_usage_percent": round(cpu, 2),
            "memory_usage_percent": round(mem, 2),
            "runtime_hours_24h": round(runtime, 2),
            "storage_gb": round(storage, 2),
            "request_count_24h": requests,
            "error_rate_percent": round(error_rate, 3),
            "latency_ms": round(latency, 2),
            "cost_24h": round(cost_24h, 2),
            "cost_30d_forecast": round(cost_30d_forecast, 2),
            "energy_kwh_24h": round(energy_kwh_24h, 3),
            "carbon_kgco2e_24h": round(carbon_kgco2e_24h, 3),
            "carbon_intensity_gco2_per_kwh": round(carbon_intensity, 2),
            # encoded categorical features
            "environment": env_code,
            "cloud_service_type": service_code,
            "workflow_criticality": crit_code,
            "public_exposure": public_code,
            "monitoring_enabled": monitoring_code,
            # targets
            "cost_30d": round(cost_30d, 2),
            "energy_kwh_30d": round(energy_kwh_30d, 3),
            "carbon_kgco2e_30d": round(carbon_kgco2e_30d, 3),
        })
    return rows


def build_dataframe() -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_SEED)
    workloads = load_workloads()
    all_rows: list[dict] = []
    for workload in workloads:
        all_rows.extend(generate_rows(workload, rng))

    column_order = ["workload_id"] + FEATURE_COLUMNS + TARGET_COLUMNS
    df = pd.DataFrame(all_rows, columns=column_order)
    return df


def main() -> None:
    df = build_dataframe()
    df.to_csv(OUTPUT_CSV_PATH, index=False)

    n_workloads = df["workload_id"].nunique()
    print(f"[done] wrote {len(df)} rows for {n_workloads} workloads to "
          f"{OUTPUT_CSV_PATH}")
    print(f"[done] columns ({len(df.columns)}): {list(df.columns)}")
    per_wl = df.groupby("workload_id").size()
    print(f"[done] rows per workload: min={per_wl.min()}, max={per_wl.max()}")


if __name__ == "__main__":
    main()
