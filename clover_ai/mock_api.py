"""Mock Data Controller API — integration surface for the SE backend.

Exposes the §11.9 endpoints as a FastAPI APIRouter the SE team can mount:

    from mock_api import router as mock_router
    app.include_router(mock_router)

Or run standalone for local testing / driving a live demo:

    python mock_api.py            # serves on http://localhost:8001

Endpoints (ARCHITECTURE.md §11.9):
    GET  /api/mock/scenarios
    POST /api/mock/trigger/{scenario_id}
    POST /api/mock/reset
    POST /api/mock/stream/start
    POST /api/mock/stream/stop
    GET  /api/mock/status

The controller posts generated telemetry to MOCK_INGEST_URL
(default http://localhost:8000/api/telemetry/ingest). Override via env var.
"""
from __future__ import annotations

import importlib.util
import os

from fastapi import APIRouter, HTTPException

from ml.common import paths


def _load_controller_class():
    """Load controllers/controller.py by path (hyphenated dir isn't importable)."""
    ctrl_path = paths.REPO_ROOT / "mock-data-generator" / "controllers" / "controller.py"
    spec = importlib.util.spec_from_file_location("mockgen_controller", ctrl_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MockController


INGEST_URL = os.environ.get("MOCK_INGEST_URL",
                            "http://localhost:8000/api/telemetry/ingest")
STREAM_INTERVAL = float(os.environ.get("MOCK_STREAM_INTERVAL", "3.0"))

MockController = _load_controller_class()
controller = MockController(ingest_url=INGEST_URL, interval_seconds=STREAM_INTERVAL)

router = APIRouter(prefix="/api/mock", tags=["mock-data-controller"])


@router.get("/scenarios")
def list_scenarios():
    return {"success": True, "data": controller.list_scenarios()}


@router.post("/trigger/{scenario_id}")
def trigger(scenario_id: str):
    try:
        return {"success": True, "data": controller.trigger(scenario_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_id}")


@router.post("/reset")
def reset():
    return {"success": True, "data": controller.reset()}


@router.post("/stream/start")
def stream_start():
    return {"success": True, "data": controller.start_stream()}


@router.post("/stream/stop")
def stream_stop():
    return {"success": True, "data": controller.stop_stream()}


@router.get("/status")
def status():
    return {"success": True, "data": controller.status()}


def build_app():
    """Standalone app for local testing."""
    from fastapi import FastAPI
    app = FastAPI(title="CloudGuard GreenOps — Mock Data Controller")
    app.include_router(router)
    return app


app = build_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
