"""Tests for the XGBoost 30-day forecaster (task 4.2).

Covers Requirement 6.1 (XGBoost produces a 30-day cost/energy/carbon forecast)
and Requirement 6.3 (graceful deterministic fallback when the model is
unavailable). Forecast values are additionally asserted non-negative
(Requirement 6.4).

The model-path tests train the artifact on demand if it is missing, so the
suite is self-contained.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from backend.modules.next_best_action.xgboost_forecast import (
    FALLBACK_MODEL_NAME,
    FORECAST_HORIZON_DAYS,
    MODEL_NAME,
    MODEL_PATH,
    XGBoostForecaster,
)
from backend.schemas.recommendation import ForecastModelResult
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module", autouse=True)
def _ensure_model_trained():
    """Train the forecast bundle once if it is not already present."""
    if not MODEL_PATH.exists():
        from backend.ml.train_xgboost import main as train_main

        train_main()
    assert MODEL_PATH.exists()
    yield


@pytest.fixture(scope="module")
def forecaster() -> XGBoostForecaster:
    return XGBoostForecaster()


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


def _make_workload(**overrides) -> Workload:
    base = dict(
        workload_id="wl-test-001",
        workload_name="Test Workload",
        workload_type="compute",
        cloud_service_type="vm",
        environment="testing",
        region="us-east-1",
        owner_team="platform",
        construction_workflow="bim_model_data_processing",
        workflow_criticality="low",
        status="healthy",
    )
    base.update(overrides)
    return Workload(**base)


def _assert_finite_non_negative(result: ForecastModelResult) -> None:
    for value in (
        result.predicted_cost_30d,
        result.predicted_energy_kwh_30d,
        result.predicted_carbon_kgco2e_30d,
    ):
        assert isinstance(value, float)
        assert math.isfinite(value)
        assert value >= 0.0


# --------------------------------------------------------------------------- #
# Model path (Requirement 6.1)
# --------------------------------------------------------------------------- #
def test_forecaster_loads_trained_models(forecaster):
    assert forecaster.is_available is True
    assert forecaster.feature_columns and len(forecaster.feature_columns) == 17


def test_model_forecast_is_finite_non_negative(forecaster):
    telemetry = _make_telemetry()
    workload = _make_workload()
    result = forecaster.forecast(telemetry, workload)

    assert isinstance(result, ForecastModelResult)
    assert result.model_name == MODEL_NAME
    _assert_finite_non_negative(result)


def test_model_forecast_without_workload_context(forecaster):
    # Workload context is optional; neutral defaults are used for categoricals.
    result = forecaster.forecast(_make_telemetry(), None)
    assert result.model_name == MODEL_NAME
    _assert_finite_non_negative(result)


def test_model_forecast_responds_to_higher_usage(forecaster):
    """A higher-consumption snapshot should not forecast less cost than a low one."""
    low = forecaster.forecast(
        _make_telemetry(cost_24h=10.0, energy_kwh_24h=5.0, carbon_kgco2e_24h=2.0),
        _make_workload(),
    )
    high = forecaster.forecast(
        _make_telemetry(
            cost_24h=500.0, energy_kwh_24h=300.0, carbon_kgco2e_24h=120.0,
            cost_30d_forecast=15000.0,
        ),
        _make_workload(),
    )
    assert high.predicted_cost_30d >= low.predicted_cost_30d


# --------------------------------------------------------------------------- #
# Fallback path (Requirement 6.3)
# --------------------------------------------------------------------------- #
def test_fallback_when_model_file_absent(tmp_path):
    missing = tmp_path / "does_not_exist.joblib"
    forecaster = XGBoostForecaster(model_path=missing)
    assert forecaster.is_available is False

    telemetry = _make_telemetry(
        cost_24h=24.0, energy_kwh_24h=12.0, carbon_kgco2e_24h=4.8
    )
    result = forecaster.forecast(telemetry, _make_workload())

    assert result.model_name == FALLBACK_MODEL_NAME
    # Deterministic: current_24h x 30 for each dimension.
    assert result.predicted_cost_30d == pytest.approx(24.0 * FORECAST_HORIZON_DAYS)
    assert result.predicted_energy_kwh_30d == pytest.approx(
        12.0 * FORECAST_HORIZON_DAYS
    )
    assert result.predicted_carbon_kgco2e_30d == pytest.approx(
        4.8 * FORECAST_HORIZON_DAYS
    )


def test_fallback_when_model_file_unloadable(tmp_path):
    corrupt = tmp_path / "corrupt.joblib"
    corrupt.write_bytes(b"not a real joblib payload")
    forecaster = XGBoostForecaster(model_path=corrupt)
    assert forecaster.is_available is False

    telemetry = _make_telemetry(
        cost_24h=100.0, energy_kwh_24h=40.0, carbon_kgco2e_24h=16.0
    )
    result = forecaster.forecast(telemetry, None)

    assert result.model_name == FALLBACK_MODEL_NAME
    assert result.predicted_cost_30d == pytest.approx(100.0 * FORECAST_HORIZON_DAYS)
    assert result.predicted_energy_kwh_30d == pytest.approx(
        40.0 * FORECAST_HORIZON_DAYS
    )
    assert result.predicted_carbon_kgco2e_30d == pytest.approx(
        16.0 * FORECAST_HORIZON_DAYS
    )


def test_fallback_forecast_is_non_negative_for_zero_telemetry(tmp_path):
    missing = tmp_path / "none.joblib"
    forecaster = XGBoostForecaster(model_path=missing)
    result = forecaster.forecast(
        _make_telemetry(cost_24h=0.0, energy_kwh_24h=0.0, carbon_kgco2e_24h=0.0),
        None,
    )
    _assert_finite_non_negative(result)
    assert result.predicted_cost_30d == 0.0
