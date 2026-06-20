"""Telemetry generation for the live mock data system (ARCHITECTURE.md §4.6, §10.6).

Pure functions: given a workload (and optionally an active scenario), produce a
fresh telemetry snapshot. The controller layer owns state and streaming; this
module only generates values.

Modes supported (via the controller):
  * healthy baseline stream  -> snapshot() with no active scenario
  * triggered issue scenario -> snapshot() with an active scenario id
  * reset                    -> controller clears scenarios; back to baseline
  * continuous stream        -> controller calls snapshot() on an interval
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from ml.common import data

# Small live jitter so a streamed dashboard looks alive without flipping a
# healthy workload into an anomaly. Relative std-dev per field.
_LIVE_JITTER = {
    "cpu_usage_percent": 0.06,
    "memory_usage_percent": 0.05,
    "request_count_24h": 0.08,
    "error_rate_percent": 0.10,
    "latency_ms": 0.06,
    "energy_kwh_24h": 0.04,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jitter(value, rel_std, rng):
    if not isinstance(value, (int, float)):
        return value
    return round(float(max(0.0, value * (1.0 + rng.normal(0.0, rel_std)))), 3)


def snapshot(workload_id: str, scenario_id: str | None = None,
             rng: np.random.Generator | None = None) -> dict:
    """Build a telemetry snapshot for a workload.

    If scenario_id is set, the scenario patch is applied on top of the healthy
    baseline (the patch values are NOT jittered, so triggers are deterministic).
    """
    rng = rng or np.random.default_rng()
    t = data.get_baseline(workload_id)

    # Live jitter on healthy fields first.
    for field, std in _LIVE_JITTER.items():
        if field in t:
            t[field] = _jitter(t[field], std, rng)
    # Keep cost coherent with hourly rate * runtime.
    if "cost_per_hour" in t and "runtime_hours_24h" in t:
        t["cost_24h"] = round(t["cost_per_hour"] * t["runtime_hours_24h"], 3)
        t["cost_30d_forecast"] = round(t["cost_24h"] * 30.0, 3)

    if scenario_id:
        sc = data.get_scenario(scenario_id)
        if sc:
            t.update(sc["patch"])  # deterministic override

    t["timestamp"] = _now_iso()
    return t


def snapshot_all(active_scenarios: dict[str, str] | None = None,
                 rng: np.random.Generator | None = None) -> list[dict]:
    """Snapshot for every workload. active_scenarios maps workload_id -> scenario_id."""
    active_scenarios = active_scenarios or {}
    rng = rng or np.random.default_rng()
    out = []
    for wl in data.load_workloads():
        wid = wl["workload_id"]
        out.append(snapshot(wid, active_scenarios.get(wid), rng))
    return out


__all__ = ["snapshot", "snapshot_all"]
