"""FastAPI application factory and cross-cutting production safeguards."""

from __future__ import annotations

from contextlib import asynccontextmanager
import re
import time
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.core.errors import RevivePayError
from app.core.logging import configure_logging, get_logger, log_context

logger = get_logger("api")
RESPONSE_TIME_HEADER = "X-Response-Time-ms"
REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class StartupSecurityError(RuntimeError):
    """A protected profile cannot serve operational routes with this configuration.

    Raised before any route is registered. The message names the failed condition
    and never the configured value (Requirement 9.9, 17.5).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"Startup refused: {reason}")
        self.reason = reason


def _enforce_startup_security(settings: Settings) -> None:
    """Fail startup for a protected profile missing required security configuration.

    Settings validation already rejects these combinations. Repeating the gate at
    the application boundary means a configuration reaching ``create_app`` by any
    other route still cannot serve operational endpoints.
    """
    policy = settings.profile_policy
    if not policy.requires_secret_authentication:
        return
    if settings.auth_mode != "api_key":
        raise StartupSecurityError(f"the {policy.profile} profile requires api_key authentication")
    if not settings.api_key:
        raise StartupSecurityError(f"the {policy.profile} profile requires a configured API key")
    if not settings.auth_scopes:
        raise StartupSecurityError(f"the {policy.profile} profile requires at least one configured operation scope")
    if not policy.allows_wildcard_cors_origins and "*" in settings.cors_origins:
        raise StartupSecurityError(f"the {policy.profile} profile requires explicit CORS origins")


def _build_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        from app.core.container import get_clock
        logger.info("service ready | env=%s | prefix=%s | simulation_time=%s", settings.environment, settings.api_prefix, get_clock(settings).now().isoformat())
        # Non-secret profile evidence only: no API key, credential, or database URL.
        logger.info("environment profile | %s", " ".join(f"{key}={value}" for key, value in settings.profile_summary().items()))
        logger.info("payment execution is synthetic only; no real money moves")
        yield
    return lifespan


def _envelope(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _describe_validation_error(exc: RequestValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = [str(item) for item in error.get("loc", []) if item != "body"]
        parts.append(f"{'.'.join(location) or 'request'}: {error.get('msg', 'invalid value')}")
    return "; ".join(parts) or "Request validation failed."


def _request_id(request: Request) -> str:
    supplied = request.headers.get(REQUEST_ID_HEADER, "")
    return supplied if _REQUEST_ID_RE.fullmatch(supplied) else uuid4().hex


def _apply_security_headers(response: JSONResponse | object, *, transport_security: bool) -> None:
    # Response is deliberately duck-typed to include Starlette streaming responses.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if transport_security:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    _enforce_startup_security(settings)
    app = FastAPI(title=settings.app_name, description=settings.app_description, version=settings.version, docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json", lifespan=_build_lifespan(settings))

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials="*" not in settings.cors_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Accept", "Authorization", "Content-Type", REQUEST_ID_HEADER, "Idempotency-Key"],
            expose_headers=[REQUEST_ID_HEADER, RESPONSE_TIME_HEADER],
            max_age=600,
        )

    from app.core.rate_limiter import RateLimitExceeded, SlidingWindowRateLimiter, extract_client_ip
    rate_limiter = SlidingWindowRateLimiter(requests_per_minute=settings.rate_limit_requests_per_minute)

    @app.middleware("http")
    async def protect_and_observe_request(request: Request, call_next):
        request_id = _request_id(request)
        request.state.request_id = request_id
        started = time.perf_counter()
        with log_context(request_id=request_id):
            client_key = extract_client_ip(request.headers, request.client.host if request.client else "127.0.0.1")
            # Enforce sliding window rate limit for mutating or demo requests (disabled in test profile)
            if request.method in ("POST", "PUT", "DELETE", "PATCH") and settings.environment_profile != "test":
                try:
                    rate_limiter.check(client_key)
                except RateLimitExceeded as exc:
                    response = JSONResponse(
                        status_code=exc.http_status,
                        content=_envelope(exc.code, exc.message),
                        headers=exc.headers,
                    )
                    _apply_security_headers(response, transport_security=settings.profile_policy.requires_transport_security)
                    return response

            declared_size = request.headers.get("content-length")
            if declared_size and declared_size.isdigit() and int(declared_size) > settings.max_request_body_bytes:
                response = JSONResponse(status_code=413, content=_envelope("PAYLOAD_TOO_LARGE", "Request body exceeds the configured limit."))
            else:
                response = await call_next(request)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            response.headers[REQUEST_ID_HEADER] = request_id
            response.headers[RESPONSE_TIME_HEADER] = f"{elapsed_ms:.2f}"
            _apply_security_headers(response, transport_security=settings.profile_policy.requires_transport_security)
            logger.info("request complete | method=%s path=%s status=%s duration_ms=%.2f", request.method, request.url.path, response.status_code, elapsed_ms)
            return response

    @app.exception_handler(RevivePayError)
    async def handle_domain_error(_: Request, exc: RevivePayError) -> JSONResponse:
        logger.info("domain error | code=%s", exc.code)
        return JSONResponse(status_code=exc.http_status, content=_envelope(exc.code, exc.message), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content=_envelope("VALIDATION_ERROR", _describe_validation_error(exc)))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error | method=%s path=%s type=%s", request.method, request.url.path, type(exc).__name__)
        return JSONResponse(status_code=500, content=_envelope("INTERNAL_ERROR", "An unexpected internal error occurred."))

    from app.api.router import api_router, root_router
    app.include_router(root_router)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
