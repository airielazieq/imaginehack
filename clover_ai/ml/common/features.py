"""Feature definitions and deterministic categorical encoders.

Single source of truth for the feature sets referenced in ARCHITECTURE.md
§8.4 (Isolation Forest) and §8.8 / §10.9 (XGBoost). Encoders are fixed maps
(not fitted) so training and live inference always agree, and so a frozen model
(§8.14) keeps producing identical scores for identical input.
"""
from __future__ import annotations

# ----------------------------------------------------------------------------
# Categorical encodings (fixed ordinal maps — stable across train & inference)
# ----------------------------------------------------------------------------
ENVIRONMENT_MAP = {"development": 0, "testing": 1, "staging": 2, "production": 3}
CLOUD_SERVICE_MAP = {
    "vm": 0, "container": 1, "serverless": 2, "pipeline": 3,
    "storage": 4, "database": 5,
}
WORKFLOW_CRITICALITY_MAP = {"low": 0, "medium": 1, "high": 2, "critical": 3}
VULN_SEVERITY_MAP = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
WORKLOAD_TYPE_MAP = {
    "Field App": 0, "IoT Dashboard": 1, "BIM Processing Job": 2, "Storage": 3,
    "Batch Job": 4, "Pipeline": 5, "VM": 6, "Database": 7,
}
REGION_MAP = {"ap-southeast-1": 0, "ap-southeast-2": 1, "us-east-1": 2, "eu-west-1": 3}


def _enc(value, mapping, default=0):
    if isinstance(value, str):
        return mapping.get(value.strip().lower() if value.strip().lower() in mapping else value, default)
    return default


def _enc_bool(value) -> int:
    return 1 if bool(value) else 0


# ----------------------------------------------------------------------------
# Isolation Forest features (ARCHITECTURE.md §8.4)
# ----------------------------------------------------------------------------
ISO_FOREST_FEATURES = [
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
    "environment_encoded",
    "cloud_service_type_encoded",
    "workflow_criticality_encoded",
    "public_exposure_encoded",
    "public_storage_encoded",
    "monitoring_enabled_encoded",
    "vulnerability_severity_encoded",
]

# ----------------------------------------------------------------------------
# XGBoost forecast features (ARCHITECTURE.md §8.8 / §10.9)
# ----------------------------------------------------------------------------
XGB_FEATURES = [
    "workload_type_encoded",
    "cloud_service_type_encoded",
    "environment_encoded",
    "region_encoded",
    "workflow_criticality_encoded",
    "cpu_usage_percent",
    "memory_usage_percent",
    "runtime_hours_24h",
    "storage_gb",
    "request_count_24h",
    "error_rate_percent",
    "latency_ms",
    "cost_24h",
    "energy_kwh_24h",
    "carbon_kgco2e_24h",
    "carbon_intensity_gco2_per_kwh",
    "public_exposure_encoded",
    "monitoring_enabled_encoded",
]

XGB_TARGETS = ["target_cost_30d", "target_energy_kwh_30d", "target_carbon_kgco2e_30d"]


def encode_telemetry(t: dict) -> dict:
    """Augment a raw telemetry dict with all *_encoded fields. Non-destructive."""
    out = dict(t)
    out["environment_encoded"] = _enc(t.get("environment"), ENVIRONMENT_MAP)
    out["cloud_service_type_encoded"] = _enc(t.get("cloud_service_type"), CLOUD_SERVICE_MAP)
    out["workflow_criticality_encoded"] = _enc(t.get("workflow_criticality"), WORKFLOW_CRITICALITY_MAP)
    out["vulnerability_severity_encoded"] = _enc(t.get("vulnerability_severity"), VULN_SEVERITY_MAP)
    out["workload_type_encoded"] = _enc(t.get("workload_type"), WORKLOAD_TYPE_MAP)
    out["region_encoded"] = _enc(t.get("region"), REGION_MAP)
    out["public_exposure_encoded"] = _enc_bool(t.get("public_exposure"))
    out["public_storage_encoded"] = _enc_bool(t.get("public_storage"))
    out["monitoring_enabled_encoded"] = _enc_bool(t.get("monitoring_enabled", True))
    return out


def to_feature_row(t: dict, feature_list: list[str]) -> list[float]:
    """Build an ordered numeric feature vector for the given feature list.
    Missing numeric fields default to 0.0 so inference never crashes on a
    partial telemetry patch (the ingestion layer fills baselines first)."""
    enc = encode_telemetry(t)
    row = []
    for f in feature_list:
        v = enc.get(f, 0.0)
        try:
            row.append(float(v))
        except (TypeError, ValueError):
            row.append(0.0)
    return row
