"""Tests for the mock data service (task 2.2).

Covers Requirements 19.2 (scenario trigger -> telemetry injection + pipeline
event), 19.3 (continuous streaming start/stop), and 19.4 (reset to healthy
baseline).

A temporary SQLite database is configured via ``CLOVER_DB_PATH`` before the app
config is imported so tests never touch the real ``clover.db``. Async methods
are driven with ``asyncio.run`` since the project does not use pytest-asyncio.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

# --- Configure an isolated temp DB BEFORE importing config/services ----------
_TMP_DIR = tempfile.mkdtemp(prefix="clover_mock_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_clover.db")
os.environ["CLOVER_DB_PATH"] = _TMP_DB

from backend.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from backend.core.database import init_db  # noqa: E402
from backend.core.event_bus import Event, EventType, event_bus  # noqa: E402
from backend.services import telemetry_service, workload_service  # noqa: E402
from backend.services.mock_data_service import MockDataService  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _schema():
    init_db()
    yield


@pytest.fixture()
def service():
    return MockDataService()


# --- Startup seeding ---------------------------------------------------------
def test_seed_workloads_upserts_all_sample_workloads(service):
    seeded = service.seed_workloads()
    assert len(seeded) >= 8
    # Known demo targets must be present.
    for wid in ("wl-bim-processor-001", "wl-field-app-001", "wl-doc-storage-001"):
        assert wid in seeded
        assert workload_service.get_workload(wid) is not None


def test_seed_healthy_baseline_persists_snapshot_per_workload(service):
    service.seed_workloads()
    count = asyncio.run(service.seed_healthy_baseline())
    assert count >= 8
    history = telemetry_service.get_telemetry_history("wl-bim-processor-001", limit=1)
    assert len(history) == 1


# --- Scenario listing --------------------------------------------------------
def test_list_scenarios_returns_seven_without_payload(service):
    scenarios = service.list_scenarios()
    assert len(scenarios) == 7
    sample = scenarios[0]
    assert "scenario_id" in sample
    assert "telemetry" not in sample  # payload withheld from the list view
    assert sample["expected_execution_path"] is not None


# --- Scenario trigger: persists telemetry + emits TELEMETRY_INGESTED ---------
def test_trigger_scenario_persists_and_emits_event(service):
    service.seed_workloads()

    received: list[Event] = []

    async def _handler(event: Event) -> None:
        received.append(event)

    event_bus.subscribe(EventType.TELEMETRY_INGESTED, _handler)
    try:
        async def _run():
            result = await service.trigger_scenario("trigger_idle_dev_server")
            # Allow fire-and-forget publish tasks to run.
            await asyncio.sleep(0.05)
            return result

        result = asyncio.run(_run())
    finally:
        event_bus.unsubscribe(EventType.TELEMETRY_INGESTED, _handler)

    # Telemetry persisted for the targeted workload.
    assert result["workload_id"] == "wl-bim-processor-001"
    history = telemetry_service.get_telemetry_history("wl-bim-processor-001", limit=1)
    assert len(history) == 1
    assert history[0]["cpu_usage_percent"] == pytest.approx(4.0)

    # Event emitted so the detection pipeline can react.
    matching = [
        e for e in received
        if e.payload.get("workload_id") == "wl-bim-processor-001"
    ]
    assert matching, "expected a TELEMETRY_INGESTED event for the scenario workload"


def test_trigger_unknown_scenario_raises(service):
    with pytest.raises(KeyError):
        asyncio.run(service.trigger_scenario("does_not_exist"))


# --- Reset -------------------------------------------------------------------
def test_reset_restores_healthy_baseline_and_clears_state(service):
    service.seed_workloads()
    asyncio.run(service.trigger_scenario("trigger_cost_spike"))
    assert "trigger_cost_spike" in service.status()["triggered_scenarios"]

    result = asyncio.run(service.reset())

    assert result["baseline_snapshots"] >= 8
    assert service.status()["triggered_scenarios"] == []
    # After reset the freshest snapshot for the cost-spike target is healthy.
    history = telemetry_service.get_telemetry_history("wl-costly-vm-001", limit=1)
    assert history[0]["cost_30d_forecast"] == pytest.approx(324.0)  # baseline, not 4464


# --- Continuous streaming ----------------------------------------------------
def test_stream_start_stop_and_status(service):
    service.seed_workloads()

    async def _run():
        started = await service.start_stream()
        # Starting twice is a no-op.
        started_again = await service.start_stream()
        await asyncio.sleep(0.05)
        streaming_flag = service.is_streaming
        stopped = await service.stop_stream()
        stopped_again = await service.stop_stream()
        return started, started_again, streaming_flag, stopped, stopped_again

    started, started_again, streaming_flag, stopped, stopped_again = asyncio.run(_run())
    assert started is True
    assert started_again is False
    assert streaming_flag is True
    assert stopped is True
    assert stopped_again is False
    assert service.is_streaming is False
