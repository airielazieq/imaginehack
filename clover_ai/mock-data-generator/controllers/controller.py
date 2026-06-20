"""Stateful mock data controller (ARCHITECTURE.md §10.2, §10.6, §10.7).

Owns: which scenarios are active, the continuous-stream background thread, and
reset. Sends telemetry to the ingestion API (POST /api/telemetry/ingest). Designed
to be driven by the FastAPI router in api.py, or used directly from a script.

The streamer tolerates a missing/unreachable backend (it logs and keeps going),
so the mock system can be exercised standalone before the SE backend is up.
"""
from __future__ import annotations

import importlib.util
import threading
import time

import numpy as np

from ml.common import data, paths


def _load_generator():
    """Load streams/generator.py by path. The 'mock-data-generator' directory
    contains a hyphen and cannot be imported as a normal package, so we load the
    module explicitly. generator.py itself imports the valid `ml.common` package."""
    gen_path = paths.REPO_ROOT / "mock-data-generator" / "streams" / "generator.py"
    spec = importlib.util.spec_from_file_location("mockgen_generator", gen_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = _load_generator()


class MockController:
    def __init__(self, ingest_url: str = "http://localhost:8000/api/telemetry/ingest",
                 interval_seconds: float = 3.0):
        self.ingest_url = ingest_url
        self.interval_seconds = interval_seconds
        self._active: dict[str, str] = {}        # workload_id -> scenario_id
        self._streaming = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._rng = np.random.default_rng()
        self._last_batch: list[dict] = []

    # -- scenarios -----------------------------------------------------------
    def list_scenarios(self) -> list[dict]:
        return [
            {"scenario_id": s["scenario_id"], "title": s["title"],
             "target_workload": s["target_workload"], "expected": s["expected"]}
            for s in data.load_scenarios()
        ]

    def trigger(self, scenario_id: str) -> dict:
        sc = data.get_scenario(scenario_id)
        if not sc:
            raise KeyError(scenario_id)
        with self._lock:
            self._active[sc["target_workload"]] = scenario_id
        snap = generator.snapshot(sc["target_workload"], scenario_id, self._rng)
        self._send(snap)
        return {"triggered": scenario_id, "target_workload": sc["target_workload"],
                "telemetry": snap}

    def reset(self) -> dict:
        """§10.7: clear active scenarios and push healthy telemetry for all."""
        with self._lock:
            self._active.clear()
        batch = generator.snapshot_all({}, self._rng)
        for snap in batch:
            self._send(snap)
        return {"reset": True, "workloads": len(batch)}

    # -- streaming -----------------------------------------------------------
    def start_stream(self) -> dict:
        with self._lock:
            if self._streaming:
                return self.status()
            self._streaming = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self.status()

    def stop_stream(self) -> dict:
        with self._lock:
            self._streaming = False
        return self.status()

    def status(self) -> dict:
        return {
            "streaming": self._streaming,
            "interval_seconds": self.interval_seconds,
            "active_scenarios": dict(self._active),
            "ingest_url": self.ingest_url,
            "workloads": len(data.load_workloads()),
        }

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._streaming:
                    break
                active = dict(self._active)
            self._last_batch = generator.snapshot_all(active, self._rng)
            for snap in self._last_batch:
                self._send(snap)
            time.sleep(self.interval_seconds)

    # -- transport -----------------------------------------------------------
    def _send(self, telemetry: dict) -> None:
        try:
            import requests
            requests.post(self.ingest_url, json=telemetry, timeout=2)
        except Exception:  # noqa: BLE001 - standalone-tolerant (backend may be down)
            pass


__all__ = ["MockController"]
