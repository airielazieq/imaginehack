"""Loaders for the static data deliverables. Everything reads from the JSON
files in mock-data-generator/data so the files remain the single source of truth."""
from __future__ import annotations

import json
from functools import lru_cache

from . import paths


@lru_cache(maxsize=1)
def load_workloads() -> list[dict]:
    with open(paths.SAMPLE_WORKLOADS, encoding="utf-8") as f:
        return json.load(f)["workloads"]


@lru_cache(maxsize=1)
def load_baselines() -> dict[str, dict]:
    """Returns {workload_id: full_telemetry_dict}."""
    with open(paths.HEALTHY_BASELINE, encoding="utf-8") as f:
        return json.load(f)["baselines"]


@lru_cache(maxsize=1)
def load_scenarios() -> list[dict]:
    with open(paths.SCENARIO_PAYLOADS, encoding="utf-8") as f:
        return json.load(f)["scenarios"]


def get_baseline(workload_id: str) -> dict:
    return dict(load_baselines()[workload_id])


def get_scenario(scenario_id: str) -> dict | None:
    for s in load_scenarios():
        if s["scenario_id"] == scenario_id:
            return s
    return None


def apply_scenario(workload_id: str, scenario_id: str) -> dict:
    """Return baseline telemetry for a workload with a scenario patch applied."""
    base = get_baseline(workload_id)
    sc = get_scenario(scenario_id)
    if sc:
        base.update(sc["patch"])
    return base
