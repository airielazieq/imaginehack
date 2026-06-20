"""Mock data generator and controller service (task 2.2).

This service is the engine behind the demo. It owns:

- **Startup seeding** - upsert the canonical workloads from
  ``mock_data/sample_workloads.json`` and (optionally) seed one healthy
  telemetry snapshot per workload so the dashboard starts "green".
- **Scenario triggers** - given a ``scenario_id`` from
  ``mock_data/scenario_payloads.json``, persist the engineered telemetry
  snapshot and emit ``TELEMETRY_INGESTED`` so the detection-to-remediation
  pipeline reacts exactly as it would for real ingestion.
- **Reset** - return every workload to its healthy baseline (persist healthy
  snapshots + emit events) and clear transient demo state (stop the stream,
  forget triggered scenarios, best-effort clear demo issues/alerts).
- **Continuous streaming** - a background asyncio task that emits telemetry for
  every workload every 3-10s with small random variation around the healthy
  baseline, with start/stop controls and a status flag.
- **Scenario listing** - expose scenario metadata (sans payload) for the API.

All telemetry is routed through the same ``telemetry_service.persist_snapshot``
+ ``event_bus`` path used by the real ingestion API (``api/telemetry.py``), so
downstream modules cannot tell mock data from "real" data. The service does not
own Issue/Recommendation state; it reacts via events like everything else.

The module exposes a singleton :data:`mock_data_service` plus thin module-level
convenience wrappers (:func:`seed_workloads`, :func:`startup`) that the app
lifespan / mock controller (task 2.3) can call without importing the class.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.config import MOCK_DATA_DIR, load_json_config
from backend.core.database import connection
from backend.core.event_bus import Event, EventType, event_bus
from backend.schemas.telemetry import TelemetrySnapshot
from backend.schemas.workload import Workload
from backend.services import telemetry_service, workload_service

logger = logging.getLogger("clover.services.mock_data")

# --- Mock data file locations ------------------------------------------------
_SAMPLE_WORKLOADS_FILE = MOCK_DATA_DIR / "sample_workloads.json"
_HEALTHY_BASELINE_FILE = MOCK_DATA_DIR / "healthy_baseline.json"
_SCENARIO_PAYLOADS_FILE = MOCK_DATA_DIR / "scenario_payloads.json"

# --- Streaming configuration -------------------------------------------------
# Per spec 12: continuous stream emits telemetry every 3-10 seconds.
_STREAM_MIN_INTERVAL_S = 3.0
_STREAM_MAX_INTERVAL_S = 10.0

# Telemetry fields that receive small random jitter while streaming. Security
# flags, categorical fields, and structural fields are intentionally left
# untouched so the stream stays "healthy" until a scenario is triggered.
_JITTER_FIELDS = (
    "cpu_usage_percent",
    "memory_usage_percent",
    "error_rate_percent",
    "latency_ms",
    "request_count_24h",
    "cost_per_hour",
    "cost_24h",
    "cost_30d_forecast",
    "energy_kwh_24h",
    "carbon_kgco2e_24h",
)

# Fields capped at 100 (percentages) when jittering.
_PERCENT_FIELDS = {
    "cpu_usage_percent",
    "memory_usage_percent",
    "error_rate_percent",
}

# Monetary cap shared with the TelemetrySnapshot schema.
_COST_MAX = 999999.99


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MockDataService:
    """Stateful controller for mock workloads, scenarios, and streaming."""

    def __init__(self) -> None:
        # Loaded lazily and cached.
        self._workloads_cache: list[dict] | None = None
        self._baseline_cache: dict[str, dict] | None = None
        self._scenarios_cache: dict[str, dict] | None = None

        # Streaming state.
        self._stream_task: asyncio.Task | None = None
        self._streaming: bool = False
        self._stream_jitter: float = 0.08  # +/-8% variation around baseline

        # Transient demo state: scenarios triggered since last reset.
        self._triggered_scenarios: list[str] = []

    # ------------------------------------------------------------------ #
    # Data loading (cached)
    # ------------------------------------------------------------------ #
    def _load_workloads(self) -> list[dict]:
        if self._workloads_cache is None:
            self._workloads_cache = load_json_config(_SAMPLE_WORKLOADS_FILE)
        return self._workloads_cache

    def _load_baseline(self) -> dict[str, dict]:
        """Return healthy baseline telemetry keyed by ``workload_id``."""
        if self._baseline_cache is None:
            rows = load_json_config(_HEALTHY_BASELINE_FILE)
            self._baseline_cache = {row["workload_id"]: row for row in rows}
        return self._baseline_cache

    def _load_scenarios(self) -> dict[str, dict]:
        """Return scenarios keyed by ``scenario_id``."""
        if self._scenarios_cache is None:
            doc = load_json_config(_SCENARIO_PAYLOADS_FILE)
            scenarios = doc.get("scenarios", []) if isinstance(doc, dict) else doc
            self._scenarios_cache = {s["scenario_id"]: s for s in scenarios}
        return self._scenarios_cache

    # ------------------------------------------------------------------ #
    # Telemetry emission (shared path with the real ingestion API)
    # ------------------------------------------------------------------ #
    async def _emit_snapshot(self, snapshot: TelemetrySnapshot) -> int:
        """Persist a snapshot and emit ``TELEMETRY_INGESTED``.

        Mirrors ``api/telemetry.py`` so mock data flows through the identical
        detection pipeline. Returns the new telemetry row id.
        """
        telemetry_id = telemetry_service.persist_snapshot(snapshot)
        await event_bus.publish(
            Event(
                event_type=EventType.TELEMETRY_INGESTED,
                payload={
                    "workload_id": snapshot.workload_id,
                    "snapshot": snapshot.model_dump(mode="json"),
                },
            )
        )
        return telemetry_id

    # ------------------------------------------------------------------ #
    # Startup seeding
    # ------------------------------------------------------------------ #
    def seed_workloads(self) -> list[str]:
        """Upsert all sample workloads. Returns the seeded workload ids.

        Synchronous because it only touches the database (no event emission);
        safe to call from a synchronous lifespan/startup context.
        """
        seeded: list[str] = []
        for raw in self._load_workloads():
            workload = Workload(**raw)
            workload_service.upsert_workload(workload)
            seeded.append(workload.workload_id)
        logger.info("Seeded %d workloads from sample data", len(seeded))
        return seeded

    async def seed_healthy_baseline(self) -> int:
        """Persist one healthy telemetry snapshot per workload + emit events.

        Returns the number of snapshots emitted. Each snapshot is timestamped
        ``now`` so it is the freshest reading for its workload.
        """
        baseline = self._load_baseline()
        count = 0
        for workload_id, raw in baseline.items():
            snapshot = self._baseline_snapshot(workload_id, raw)
            if snapshot is not None:
                await self._emit_snapshot(snapshot)
                count += 1
        logger.info("Seeded healthy baseline telemetry for %d workloads", count)
        return count

    async def startup(self, *, seed_baseline: bool = True) -> dict[str, Any]:
        """Full startup routine for the app lifespan / mock controller.

        Seeds workloads, then optionally seeds a healthy baseline snapshot per
        workload so the dashboard renders a green heatmap immediately.
        """
        workload_ids = self.seed_workloads()
        baseline_count = 0
        if seed_baseline:
            baseline_count = await self.seed_healthy_baseline()
        return {
            "workloads_seeded": len(workload_ids),
            "baseline_snapshots": baseline_count,
        }

    # ------------------------------------------------------------------ #
    # Scenario listing + trigger
    # ------------------------------------------------------------------ #
    def list_scenarios(self) -> list[dict]:
        """Return scenario metadata (without the raw telemetry payload).

        Suitable for ``GET /api/mock/scenarios``.
        """
        scenarios = self._load_scenarios()
        listed: list[dict] = []
        for scenario in scenarios.values():
            listed.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "name": scenario.get("name"),
                    "description": scenario.get("description"),
                    "target_workload_id": scenario.get("target_workload_id"),
                    "expected_issue_type": scenario.get("expected_issue_type"),
                    "expected_detection_rule": scenario.get("expected_detection_rule"),
                    "expected_execution_path": scenario.get("expected_execution_path"),
                }
            )
        return listed

    def get_scenario(self, scenario_id: str) -> dict | None:
        """Return the full scenario dict (including telemetry), or ``None``."""
        return self._load_scenarios().get(scenario_id)

    async def trigger_scenario(self, scenario_id: str) -> dict[str, Any]:
        """Inject a scenario's telemetry and emit ``TELEMETRY_INGESTED``.

        Raises:
            KeyError: if ``scenario_id`` is unknown.
        """
        scenario = self.get_scenario(scenario_id)
        if scenario is None:
            raise KeyError(scenario_id)

        raw = dict(scenario["telemetry"])
        # Use a fresh timestamp so the injected reading is the most recent one.
        raw["timestamp"] = _utcnow().isoformat()
        snapshot = TelemetrySnapshot(**raw)
        telemetry_id = await self._emit_snapshot(snapshot)

        if scenario_id not in self._triggered_scenarios:
            self._triggered_scenarios.append(scenario_id)

        logger.info(
            "Triggered scenario %s on workload %s (telemetry_id=%s)",
            scenario_id,
            snapshot.workload_id,
            telemetry_id,
        )
        return {
            "scenario_id": scenario_id,
            "workload_id": snapshot.workload_id,
            "telemetry_id": telemetry_id,
            "expected_issue_type": scenario.get("expected_issue_type"),
            "expected_execution_path": scenario.get("expected_execution_path"),
        }

    # ------------------------------------------------------------------ #
    # Reset
    # ------------------------------------------------------------------ #
    async def reset(self, *, clear_demo_state: bool = True) -> dict[str, Any]:
        """Return all workloads to a healthy baseline and clear demo state.

        Steps:
        1. Stop the continuous stream if running.
        2. Forget any triggered scenarios.
        3. Best-effort clear transient demo issues/alerts (if those tables
           contain rows) so the heatmap returns to green.
        4. Persist + emit a healthy baseline snapshot for every workload.
        """
        await self.stop_stream()
        self._triggered_scenarios.clear()

        cleared = {}
        if clear_demo_state:
            cleared = self._clear_transient_state()

        baseline_count = await self.seed_healthy_baseline()
        logger.info("Reset complete: %d healthy snapshots emitted", baseline_count)
        return {
            "baseline_snapshots": baseline_count,
            "cleared": cleared,
        }

    @staticmethod
    def _clear_transient_state() -> dict[str, int]:
        """Best-effort delete of transient demo rows (issues, alerts, etc.).

        These tables are owned by later modules; deletion is wrapped defensively
        so a reset never fails if a table is missing or empty.
        """
        cleared: dict[str, int] = {}
        transient_tables = ("issues", "recommendations", "remediations", "alerts")
        try:
            with connection() as conn:
                for table in transient_tables:
                    try:
                        cur = conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names
                        cleared[table] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                    except Exception:  # noqa: BLE001 - table may not exist yet
                        cleared[table] = 0
        except Exception:  # noqa: BLE001 - never let reset fail on cleanup
            logger.warning("Transient state cleanup skipped", exc_info=True)
        return cleared

    # ------------------------------------------------------------------ #
    # Continuous streaming
    # ------------------------------------------------------------------ #
    async def start_stream(self) -> bool:
        """Start the continuous telemetry stream. Returns ``True`` if started.

        Returns ``False`` (no-op) if a stream is already running.
        """
        if self._streaming and self._stream_task is not None and not self._stream_task.done():
            return False
        self._streaming = True
        self._stream_task = asyncio.create_task(self._stream_loop())
        logger.info("Continuous telemetry stream started")
        return True

    async def stop_stream(self) -> bool:
        """Stop the continuous telemetry stream. Returns ``True`` if stopped.

        Returns ``False`` (no-op) if no stream was running.
        """
        if not self._streaming and self._stream_task is None:
            return False
        self._streaming = False
        task = self._stream_task
        self._stream_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        logger.info("Continuous telemetry stream stopped")
        return True

    def status(self) -> dict[str, Any]:
        """Return the current controller status for ``GET /api/mock/status``."""
        return {
            "streaming": self._streaming,
            "triggered_scenarios": list(self._triggered_scenarios),
            "stream_interval_seconds": [_STREAM_MIN_INTERVAL_S, _STREAM_MAX_INTERVAL_S],
        }

    @property
    def is_streaming(self) -> bool:
        return self._streaming

    async def _stream_loop(self) -> None:
        """Background loop: emit varied healthy telemetry on a 3-10s cadence."""
        baseline = self._load_baseline()
        try:
            while self._streaming:
                for workload_id, raw in baseline.items():
                    snapshot = self._varied_snapshot(workload_id, raw)
                    if snapshot is not None:
                        await self._emit_snapshot(snapshot)
                interval = random.uniform(_STREAM_MIN_INTERVAL_S, _STREAM_MAX_INTERVAL_S)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.debug("Stream loop cancelled")
            raise
        except Exception:  # noqa: BLE001 - keep the stream resilient
            logger.exception("Stream loop error; stopping stream")
            self._streaming = False

    # ------------------------------------------------------------------ #
    # Snapshot builders
    # ------------------------------------------------------------------ #
    def _baseline_snapshot(self, workload_id: str, raw: dict) -> TelemetrySnapshot | None:
        """Build a healthy snapshot from baseline data with a fresh timestamp."""
        try:
            payload = dict(raw)
            payload["timestamp"] = _utcnow().isoformat()
            return TelemetrySnapshot(**payload)
        except Exception:  # noqa: BLE001
            logger.exception("Invalid baseline telemetry for %s", workload_id)
            return None

    def _varied_snapshot(self, workload_id: str, raw: dict) -> TelemetrySnapshot | None:
        """Build a snapshot with small random jitter around the baseline."""
        try:
            payload = dict(raw)
            for field in _JITTER_FIELDS:
                if field not in payload:
                    continue
                base_value = payload[field]
                if not isinstance(base_value, (int, float)):
                    continue
                factor = 1.0 + random.uniform(-self._stream_jitter, self._stream_jitter)
                value = base_value * factor
                if field in _PERCENT_FIELDS:
                    value = max(0.0, min(100.0, value))
                elif field in ("cost_per_hour", "cost_24h", "cost_30d_forecast"):
                    value = max(0.0, min(_COST_MAX, value))
                else:
                    value = max(0.0, value)
                # request_count_24h is an integer field.
                payload[field] = int(round(value)) if field == "request_count_24h" else round(value, 4)
            payload["timestamp"] = _utcnow().isoformat()
            return TelemetrySnapshot(**payload)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to build varied telemetry for %s", workload_id)
            return None


# Module-level singleton used across the application.
mock_data_service = MockDataService()


# --- Thin module-level convenience wrappers ----------------------------------
def seed_workloads() -> list[str]:
    """Seed sample workloads via the shared singleton (see :meth:`MockDataService.seed_workloads`)."""
    return mock_data_service.seed_workloads()


async def startup(*, seed_baseline: bool = True) -> dict[str, Any]:
    """Run startup seeding via the shared singleton (see :meth:`MockDataService.startup`)."""
    return await mock_data_service.startup(seed_baseline=seed_baseline)
