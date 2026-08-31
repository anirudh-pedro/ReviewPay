"""Application factory.

``create_app()`` is the single place the HTTP surface is assembled: logging,
middleware, error handling, and routes (Requirement 1.1). Nothing in
``app/services``, ``app/ml``, ``app/workflows``, or ``app/integrations`` imports
this module, which is what keeps the domain runnable from a script or a test
without an HTTP server.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.core.errors import RevivePayError
from app.core.logging import configure_logging, get_logger

logger = get_logger("api")

RESPONSE_TIME_HEADER = "X-Response-Time-ms"


def _build_lifespan(settings: Settings):
    """Log the operating parameters a demo operator needs to see on startup."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        from app.core.container import get_clock

        logger.info(
            "%s v%s ready | env=%s | prefix=%s | simulation_time=%s",
            settings.app_name,
            settings.version,
            settings.environment,
            settings.api_prefix,
            get_clock(settings).now().isoformat(),
        )
        logger.info(
            "All payment behaviour is simulated. No real money moves in this application."
        )
        yield

    return lifespan


def _envelope(code: str, message: str) -> dict:
    """Build the standard error body (Requirement 1.8)."""
    return {"error": {"code": code, "message": message}}


def _describe_validation_error(exc: RequestValidationError) -> str:
    """Name the offending field, so a 422 is actionable (Requirement 3.6)."""
    parts: list[str] = []
    for error in exc.errors():
        location = [str(item) for item in error.get("loc", []) if item != "body"]
        field = ".".join(location) or "request"
        parts.append(f"{field}: {error.get('msg', 'invalid value')}")
    return "; ".join(parts) or "Request validation failed."


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    settings = get_settings()

    # Logging is configured before routes are registered so that import-time and
    # startup messages are formatted consistently (Requirement 1.6).
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        description=settings.app_description,
        version=settings.version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=_build_lifespan(settings),
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def add_response_time_header(request: Request, call_next):
        """Report elapsed request duration in milliseconds (Requirement 1.7).

        Uses ``perf_counter`` deliberately: this measures real wall-clock latency
        for debugging and is unrelated to the simulation clock.
        """
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        response.headers[RESPONSE_TIME_HEADER] = f"{elapsed_ms:.2f}"
        logger.debug(
            "%s %s -> %s in %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    # --- Error handling -----------------------------------------------------

    @app.exception_handler(RevivePayError)
    async def handle_domain_error(_: Request, exc: RevivePayError) -> JSONResponse:
        logger.info("domain error %s: %s", exc.code, exc.message)
        return JSONResponse(
            status_code=exc.http_status,
            content=_envelope(exc.code, exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope("VALIDATION_ERROR", _describe_validation_error(exc)),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=_envelope("INTERNAL_ERROR", "An unexpected internal error occurred."),
        )

    # --- Routes -------------------------------------------------------------
    # Imported here so that a module-level import cycle is impossible.
    from app.api.router import api_router, root_router

    app.include_router(root_router)
    app.include_router(api_router, prefix=settings.api_prefix)

    return app


app = create_app()
