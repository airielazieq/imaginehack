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
from backend.modules.detection_insight import detector
from backend.services.mock_data_service import mock_data_service

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

app.include_router(telemetry.router)
app.include_router(workloads.router)
app.include_router(mock_controller.router)
app.include_router(detection.router)
