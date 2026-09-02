"""Public liveness and database-readiness probes.

Both probes report the normalized environment profile and the authentication
*mode*. Neither returns a credential, a connection string, SQL text, or an
internal exception detail (Requirement 9.2, 9.7, 17.5).
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.auth import describe_authentication
from app.api.deps import ClockDep, SessionDep, SettingsDep
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service liveness and simulation time")
def health(settings: SettingsDep, clock: ClockDep) -> HealthResponse:
    status = describe_authentication(settings)
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=settings.version,
        environment=settings.environment,
        virtual_clock_time=clock.now(),
        environment_profile=status.environment_profile,
        authentication_mode=status.authentication_mode,
        authenticated_principal_required=status.authenticated_principal_required,
    )


@router.get("/readyz", summary="Database readiness")
def readyz(session: SessionDep, settings: SettingsDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    status = describe_authentication(settings)
    return {
        "status": "ready",
        "database": "reachable",
        "environment_profile": status.environment_profile,
        "authentication_mode": status.authentication_mode,
        "authenticated_principal_required": str(status.authenticated_principal_required).lower(),
    }
