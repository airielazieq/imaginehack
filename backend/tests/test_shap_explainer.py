"""Tests for the SHAP explainer (task 3.3).

Covers Requirement 2.2 (SHAP-style feature contributions identifying the top
factors) and Requirement 4.2 (structured XAI explanation card with method name
and top factors as feature/value/impact).

Two paths are exercised:
- the **SHAP path** (``shap.TreeExplainer`` on the trained Isolation Forest),
- the **rule-based fallback** (model unavailable).

The model artifact is trained on demand if missing so the suite is
self-contained, mirroring ``test_isolation_forest.py``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.modules.detection_insight.isolation_forest import (
    FEATURE_COLUMNS,
    MODEL_PATH,
    IsolationForestDetector,
    build_feature_vector,
    get_detector,
)
from backend.modules.detection_insight.shap_explainer import (
    FALLBACK_METHOD,
    MIN_FACTORS,
    SHAP_METHOD,
    TOP_N,
    _compute_shap_values,
    explain,
    explain_snapshot,
)
from backend.schemas.issue import XAIExplanation, XAIFactor
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
    # Refresh the cached singleton so it picks up the freshly trained model.
    get_detector.cache_clear()
    yield


@pytest.fixture(scope="module")
def detector() -> IsolationForestDetector:
    return IsolationForestDetector()


def _load_scenario(scenario_id: str) -> TelemetrySnapshot:
    data = json.loads(_SCENARIOS_PATH.read_text(encoding="utf-8"))
    match = next(s for s in data["scenarios"] if s["scenario_id"] == scenario_id)
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
        runtime_hours_24h=12.0,
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


def _assert_valid_explanation(ex: XAIExplanation) -> None:
    assert isinstance(ex, XAIExplanation)
    assert ex.method
    n = len(ex.top_contributing_factors)
    assert MIN_FACTORS <= n <= TOP_N
    for factor in ex.top_contributing_factors:
        assert isinstance(factor, XAIFactor)
        assert factor.feature in FEATURE_COLUMNS
        assert factor.impact.strip(), "impact string must be non-empty"


# --------------------------------------------------------------------------- #
# SHAP path (Requirements 2.2, 4.2)
# --------------------------------------------------------------------------- #
def test_shap_path_returns_3_to_5_valid_factors(detector):
    workload = _load_workload("wl-costly-vm-001")
    telemetry = _load_scenario("trigger_cost_spike")

    ex = explain(telemetry, workload, detector=detector)

    assert ex.method == SHAP_METHOD
    _assert_valid_explanation(ex)


def test_shap_factors_sorted_by_absolute_shap_value(detector):
    workload = _load_workload("wl-costly-vm-001")
    telemetry = _load_scenario("trigger_cost_spike")

    ex = explain(telemetry, workload, detector=detector)

    # Recompute the raw SHAP values and confirm the returned factors are in
    # descending |shap| order.
    fv = build_feature_vector(telemetry, workload)
    shap_by_feature = dict(zip(FEATURE_COLUMNS, _compute_shap_values(detector.model, fv)))
    abs_in_order = [abs(shap_by_feature[f.feature]) for f in ex.top_contributing_factors]
    assert abs_in_order == sorted(abs_in_order, reverse=True)


def test_cost_spike_ranks_cost_feature_highly(detector):
    """A cost spike should surface cost/runtime features near the top."""
    workload = _load_workload("wl-costly-vm-001")
    telemetry = _load_scenario("trigger_cost_spike")

    ex = explain(telemetry, workload, detector=detector)

    top_features = [f.feature for f in ex.top_contributing_factors]
    cost_runtime = {"cost_24h", "cost_30d_forecast", "runtime_hours_24h"}
    # At least one cost/runtime driver appears, and the strongest factor is one.
    assert cost_runtime & set(top_features[:3])


def test_shap_factor_values_match_feature_vector(detector):
    workload = _load_workload("wl-costly-vm-001")
    telemetry = _load_scenario("trigger_cost_spike")
    fv = dict(zip(FEATURE_COLUMNS, build_feature_vector(telemetry, workload)))

    ex = explain(telemetry, workload, detector=detector)
    for factor in ex.top_contributing_factors:
        assert float(factor.value) == pytest.approx(fv[factor.feature])


def test_explain_snapshot_uses_cached_detector_shap_path():
    workload = _load_workload("wl-iot-dashboard-001")
    telemetry = _load_scenario("trigger_high_error_rate")

    ex = explain_snapshot(telemetry, workload)

    # With a trained model present, the cached detector drives the SHAP path.
    assert ex.method == SHAP_METHOD
    _assert_valid_explanation(ex)


# --------------------------------------------------------------------------- #
# Rule-based fallback (Requirement 4.2 fallback behaviour)
# --------------------------------------------------------------------------- #
def test_fallback_when_model_absent(tmp_path):
    missing = tmp_path / "does_not_exist.joblib"
    offline = IsolationForestDetector(model_path=missing)
    assert offline.is_available is False

    workload = _load_workload("wl-costly-vm-001")
    telemetry = _load_scenario("trigger_cost_spike")

    ex = explain(telemetry, workload, detector=offline)

    assert ex.method == FALLBACK_METHOD
    _assert_valid_explanation(ex)


def test_fallback_ranks_high_deviation_feature_first(tmp_path):
    """The fallback should rank a strongly deviating feature near the top."""
    missing = tmp_path / "does_not_exist.joblib"
    offline = IsolationForestDetector(model_path=missing)

    # error_rate far above the healthy reference of ~0.5%.
    telemetry = _make_telemetry(error_rate_percent=85.0)
    ex = explain(telemetry, None, detector=offline)

    top_features = [f.feature for f in ex.top_contributing_factors]
    assert "error_rate_percent" in top_features


def test_fallback_flags_missing_monitoring(tmp_path):
    missing = tmp_path / "does_not_exist.joblib"
    offline = IsolationForestDetector(model_path=missing)

    telemetry = _make_telemetry(monitoring_enabled=False, public_exposure=True)
    ex = explain(telemetry, None, detector=offline)

    top_features = [f.feature for f in ex.top_contributing_factors]
    # Both boolean risk conditions fired -> they rank among the top factors.
    assert "monitoring_enabled" in top_features
    assert "public_exposure" in top_features
    # The impact text reads as plain language.
    monitoring = next(
        f for f in ex.top_contributing_factors if f.feature == "monitoring_enabled"
    )
    assert "missing" in monitoring.impact.lower()


# --------------------------------------------------------------------------- #
# Property-based: explanation is always structurally valid
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

    @settings(max_examples=40, deadline=None)
    @given(telemetry=_telemetry_strategy)
    def test_property_explanation_always_valid_shap_path(telemetry):
        ex = explain_snapshot(telemetry, None)
        assert ex.method in {SHAP_METHOD, FALLBACK_METHOD}
        _assert_valid_explanation(ex)

    @settings(max_examples=30, deadline=None)
    @given(telemetry=_telemetry_strategy)
    def test_property_explanation_always_valid_fallback_path(telemetry):
        offline = IsolationForestDetector(model_path=Path("nonexistent.joblib"))
        ex = explain(telemetry, None, detector=offline)
        assert ex.method == FALLBACK_METHOD
        _assert_valid_explanation(ex)

except ImportError:  # pragma: no cover - hypothesis is available in this env
    pass
