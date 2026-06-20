"""Tests for the Isolation Forest anomaly detector (task 3.2).

Covers Requirements 2.1 (produce anomaly_score + is_anomaly) and 2.3 (graceful
rules-only fallback when the model is unavailable).

These tests assume the model artifact has been trained via
``backend/ml/train_isolation_forest.py`` (the test module trains it on demand
if it is missing, so the suite is self-contained).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.modules.detection_insight.isolation_forest import (
    FALLBACK_MODEL_NAME,
    FEATURE_COLUMNS,
    MODEL_NAME,
    MODEL_PATH,
    CRITICALITY_CODES,
    ENV_CODES,
    SERVICE_CODES,
    IsolationForestDetector,
    build_feature_vector,
)
from backend.schemas.issue import MLResult
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload

_MOCK_DIR = Path(__file__).resolve().parents[1] / "mock_data"
_BASELINE_PATH = _MOCK_DIR / "healthy_baseline.json"
_SCENARIOS_PATH = _MOCK_DIR / "scenario_payloads.json"
_WORKLOADS_PATH = _MOCK_DIR / "sample_workloads.json"


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module", autouse=True)
def _ensure_model_trained():
    """Train the model artifact once if it is not already present."""
    if not MODEL_PATH.exists():
        from backend.ml.train_isolation_forest import main as train_main

        train_main()
    assert MODEL_PATH.exists()
    yield


@pytest.fixture(scope="module")
def detector() -> IsolationForestDetector:
    return IsolationForestDetector()


def _load_baseline(workload_id: str) -> TelemetrySnapshot:
    rows = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    match = next(r for r in rows if r["workload_id"] == workload_id)
    return TelemetrySnapshot(**match)


def _load_scenario(scenario_id: str) -> TelemetrySnapshot:
    data = json.loads(_SCENARIOS_PATH.read_text(encoding="utf-8"))
    match = next(
        s for s in data["scenarios"] if s["scenario_id"] == scenario_id
    )
    return TelemetrySnapshot(**match["telemetry"])


def _load_workload(workload_id: str) -> Workload:
    rows = json.loads(_WORKLOADS_PATH.read_text(encoding="utf-8"))
    match = next(r for r in rows if r["workload_id"] == workload_id)
    return Workload(**match)


def _make_telemetry(**overrides) -> TelemetrySnapshot:
    base = dict(
        workload_id="wl-test-001",
        cpu_usage_percent=40.0,
        memory_usage_percent=50.0,
        storage_gb=100.0,
        runtime_hours_24h=24.0,
        request_count_24h=50000,
        error_rate_percent=0.5,
        latency_ms=120.0,
        public_exposure=False,
        public_storage=False,
        vulnerability_severity="none",
        critical_vulnerability_count=0,
        access_anomaly_detected=False,
        monitoring_enabled=True,
        cost_per_hour=1.0,
        cost_24h=24.0,
        cost_30d_forecast=720.0,
        energy_kwh_24h=12.0,
        carbon_kgco2e_24h=4.8,
        carbon_intensity_gco2_per_kwh=400.0,
        timestamp=datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return TelemetrySnapshot(**base)


# --------------------------------------------------------------------------- #
# Feature extractor
# --------------------------------------------------------------------------- #
def test_feature_vector_has_17_features_in_order():
    telemetry = _make_telemetry()
    workload = _load_workload("wl-costly-vm-001")
    vec = build_feature_vector(telemetry, workload)

    assert len(vec) == len(FEATURE_COLUMNS) == 17
    assert all(isinstance(v, float) for v in vec)
    assert all(math.isfinite(v) for v in vec)


def test_feature_vector_numeric_values_map_directly():
    telemetry = _make_telemetry(
        cpu_usage_percent=12.5,
        memory_usage_percent=33.0,
        cost_24h=99.0,
        carbon_intensity_gco2_per_kwh=512.0,
    )
    workload = _load_workload("wl-costly-vm-001")
    vec = build_feature_vector(telemetry, workload)
    idx = {name: i for i, name in enumerate(FEATURE_COLUMNS)}

    assert vec[idx["cpu_usage_percent"]] == pytest.approx(12.5)
    assert vec[idx["memory_usage_percent"]] == pytest.approx(33.0)
    assert vec[idx["cost_24h"]] == pytest.approx(99.0)
    assert vec[idx["carbon_intensity_gco2_per_kwh"]] == pytest.approx(512.0)


def test_feature_vector_applies_categorical_encodings():
    # wl-costly-vm-001 => testing / vm / low
    workload = _load_workload("wl-costly-vm-001")
    telemetry = _make_telemetry(public_exposure=True, monitoring_enabled=False)
    vec = build_feature_vector(telemetry, workload)
    idx = {name: i for i, name in enumerate(FEATURE_COLUMNS)}

    assert vec[idx["environment"]] == float(ENV_CODES["testing"])
    assert vec[idx["cloud_service_type"]] == float(SERVICE_CODES["vm"])
    assert vec[idx["workflow_criticality"]] == float(CRITICALITY_CODES["low"])
    assert vec[idx["public_exposure"]] == 1.0
    assert vec[idx["monitoring_enabled"]] == 0.0


def test_feature_vector_uses_defaults_without_workload():
    telemetry = _make_telemetry()
    vec = build_feature_vector(telemetry, None)
    idx = {name: i for i, name in enumerate(FEATURE_COLUMNS)}

    # Neutral defaults: production / container / medium.
    assert vec[idx["environment"]] == float(ENV_CODES["production"])
    assert vec[idx["cloud_service_type"]] == float(SERVICE_CODES["container"])
    assert vec[idx["workflow_criticality"]] == float(CRITICALITY_CODES["medium"])


# --------------------------------------------------------------------------- #
# Model loading + scoring (Requirement 2.1)
# --------------------------------------------------------------------------- #
def test_detector_loads_trained_model(detector):
    assert detector.is_available is True
    assert detector.model is not None
    assert detector.feature_columns == FEATURE_COLUMNS


def test_score_returns_valid_ml_result(detector):
    telemetry = _load_baseline("wl-costly-vm-001")
    workload = _load_workload("wl-costly-vm-001")
    result = detector.score(telemetry, workload)

    assert isinstance(result, MLResult)
    assert result.model_name == MODEL_NAME
    assert isinstance(result.anomaly_score, float)
    assert math.isfinite(result.anomaly_score)
    assert isinstance(result.is_anomaly, bool)


def test_cost_spike_scenario_scores_more_anomalous_than_baseline(detector):
    """A cost-spike snapshot must score more anomalous than the healthy one.

    Higher anomaly_score == more anomalous (Requirement 2.1).
    """
    workload = _load_workload("wl-costly-vm-001")
    baseline = _load_baseline("wl-costly-vm-001")
    spike = _load_scenario("trigger_cost_spike")

    baseline_result = detector.score(baseline, workload)
    spike_result = detector.score(spike, workload)

    assert spike_result.anomaly_score > baseline_result.anomaly_score
    # The engineered waste scenario should trip the outlier flag.
    assert spike_result.is_anomaly is True


def test_high_error_rate_scenario_scores_more_anomalous_than_baseline(detector):
    workload = _load_workload("wl-iot-dashboard-001")
    baseline = _load_baseline("wl-iot-dashboard-001")
    scenario = _load_scenario("trigger_high_error_rate")

    baseline_result = detector.score(baseline, workload)
    scenario_result = detector.score(scenario, workload)

    assert scenario_result.anomaly_score > baseline_result.anomaly_score


# --------------------------------------------------------------------------- #
# Fallback path (Requirement 2.3)
# --------------------------------------------------------------------------- #
def test_fallback_when_model_file_absent(tmp_path):
    missing = tmp_path / "does_not_exist.joblib"
    detector = IsolationForestDetector(model_path=missing)

    assert detector.is_available is False

    telemetry = _make_telemetry()
    workload = _load_workload("wl-costly-vm-001")
    result = detector.score(telemetry, workload)

    assert result.model_name == FALLBACK_MODEL_NAME
    assert result.is_anomaly is False
    assert result.anomaly_score == 0.0


def test_fallback_when_model_file_unloadable(tmp_path):
    corrupt = tmp_path / "corrupt.joblib"
    corrupt.write_bytes(b"not a real joblib payload")
    detector = IsolationForestDetector(model_path=corrupt)

    assert detector.is_available is False
    result = detector.score(_make_telemetry(), None)
    assert result.model_name == FALLBACK_MODEL_NAME
    assert result.is_anomaly is False


# --------------------------------------------------------------------------- #
# Property-based: feature vector + score robustness
# --------------------------------------------------------------------------- #
try:
    from hypothesis import given, settings
    from hypothesis import strategies as st

    _telemetry_strategy = st.builds(
        _make_telemetry,
        cpu_usage_percent=st.floats(0, 100),
        memory_usage_percent=st.floats(0, 100),
        storage_gb=st.floats(0, 1e6),
        runtime_hours_24h=st.floats(0, 24),
        request_count_24h=st.integers(0, 10_000_000),
        error_rate_percent=st.floats(0, 100),
        latency_ms=st.floats(0, 100000),
        cost_24h=st.floats(0, 999999.99),
        cost_30d_forecast=st.floats(0, 999999.99),
        energy_kwh_24h=st.floats(0, 1e6),
        carbon_kgco2e_24h=st.floats(0, 1e6),
        carbon_intensity_gco2_per_kwh=st.floats(0, 1e6),
        public_exposure=st.booleans(),
        monitoring_enabled=st.booleans(),
    )

    @settings(max_examples=60, deadline=None)
    @given(telemetry=_telemetry_strategy)
    def test_property_feature_vector_always_17_finite_floats(telemetry):
        vec = build_feature_vector(telemetry, None)
        assert len(vec) == 17
        assert all(isinstance(v, float) and math.isfinite(v) for v in vec)

    @settings(max_examples=40, deadline=None)
    @given(telemetry=_telemetry_strategy)
    def test_property_score_always_valid_ml_result(telemetry):
        detector = IsolationForestDetector()
        result = detector.score(telemetry, None)
        assert result.model_name in {MODEL_NAME, FALLBACK_MODEL_NAME}
        assert isinstance(result.is_anomaly, bool)
        assert math.isfinite(result.anomaly_score)

except ImportError:  # pragma: no cover - hypothesis always installed here
    pass
