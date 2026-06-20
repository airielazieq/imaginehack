"""FastAPI application entry point for the Clover Cloud Intelligence Platform.

Wires together the application skeleton:
- Lifespan handler that initializes the database and tears down the event bus.
- CORS middleware for the React frontend.
- Structured JSON error envelopes for validation and unhandled errors
  (``{ "error": true, "code": ..., "message": ..., "details": ... }``).
- A health check endpoint.

Feature module routers (telemetry, workloads, detection, etc.) are added in
later tasks; this module provides the stable foundation they plug into.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.core.config import get_settings
from backend.core.database import init_db
from backend.core.event_bus import event_bus
from backend.modules.alerts import alert_engine
from backend.modules.alerts import delivery as alert_delivery
from backend.modules.detection_insight import detector
from backend.modules.next_best_action import nba_pipeline
from backend.modules.scoring import priority_scorer
from backend.services import audit_service
from backend.services.mock_data_service import mock_data_service
from backend.api import websocket as websocket_api

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("clover.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup initialization and graceful shutdown."""
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    init_db()
    # Wire Module 1 detection to react to TELEMETRY_INGESTED (idempotent).
    detector.register_subscriptions()
    # Wire Module 2 NBA pipeline to react to ISSUE_DETECTED (idempotent).
    nba_pipeline.register_subscriptions()
    # Wire the Scoring Engine to recompute on Issue/Recommendation/Remediation
    # state changes (idempotent).
    priority_scorer.register_subscriptions()
    # Wire the audit recorder to write an immutable AuditLog on each meaningful
    # lifecycle event (Issue/Recommendation/Remediation transitions) (idempotent).
    audit_service.register_subscriptions()
    # Wire the Alert engine to generate threshold-based alerts on SCORE_UPDATED
    # (idempotent).
    alert_engine.register_subscriptions()
    # Wire alert delivery + auto-resolution (deliver on ALERT_FIRED, resolve on
    # REMEDIATION_COMPLETED / healthy SCORE_UPDATED) (idempotent).
    alert_delivery.register_subscriptions()
    # Wire the WebSocket broadcaster to push real-time stream events to
    # connected dashboard clients (idempotent) and start its liveness heartbeat.
    websocket_api.register_subscriptions()
    websocket_api.start_heartbeat()
    seed_result = await mock_data_service.startup(seed_baseline=True)
    logger.info(
        "Seeded %d workloads + %d baseline snapshots",
        seed_result.get("workloads_seeded", 0),
        seed_result.get("baseline_snapshots", 0),
    )
    logger.info("Database ready; event bus active")
    try:
        yield
    finally:
        await websocket_api.stop_heartbeat()
        websocket_api.unregister_subscriptions()
        await event_bus.aclose()
        logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Secure, energy-aware cloud intelligence platform for construction-tech "
        "workloads. Simulation-mode MVP."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_response(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    """Build a standardized error envelope response."""
    body: dict = {"error": True, "code": code, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse(status_code=status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return HTTP 422 with the structured VALIDATION_ERROR envelope."""
    errors = exc.errors()
    first = errors[0] if errors else {}
    field = ".".join(str(p) for p in first.get("loc", []) if p not in ("body",))
    return _error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message=first.get("msg", "Request validation failed"),
        details={"field": field, "errors": errors},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Map HTTP exceptions to the structured error envelope."""
    code_map = {
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }
    code = code_map.get(exc.status_code, "ERROR")
    return _error_response(
        status_code=exc.status_code,
        code=code,
        message=str(exc.detail),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: log traceback and return a generic 500 envelope."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return _error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred.",
    )


@app.get("/api/health", tags=["system"])
async def health_check() -> dict:
    """Lightweight liveness probe."""
    return {
        "success": True,
        "data": {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.app_version,
        },
        "message": "Clover backend is running.",
    }


# Feature routers.
from backend.api import telemetry  # noqa: E402
from backend.api import workloads  # noqa: E402
from backend.api import mock_controller  # noqa: E402
from backend.api import detection  # noqa: E402
from backend.api import recommendations  # noqa: E402
from backend.api import approvals  # noqa: E402
from backend.api import remediation  # noqa: E402
from backend.api import scoring  # noqa: E402
from backend.api import dashboard  # noqa: E402
from backend.api import audit  # noqa: E402
from backend.api import alerts  # noqa: E402
from backend.api import mcp_log  # noqa: E402

app.include_router(telemetry.router)
app.include_router(workloads.router)
app.include_router(mock_controller.router)
app.include_router(detection.router)
app.include_router(recommendations.router)
app.include_router(approvals.router)
app.include_router(remediation.router)
app.include_router(scoring.router)
app.include_router(dashboard.router)
app.include_router(audit.router)
app.include_router(alerts.router)
app.include_router(mcp_log.router)
app.include_router(websocket_api.router)
