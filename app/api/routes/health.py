"""Health endpoint (Requirement 24.1).

Served outside ``API_PREFIX`` so a probe never needs to know the mount path.
Reports the current simulation time, which is the fastest way to confirm the
virtual clock is where a demo expects it.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ClockDep, SettingsDep
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service health and simulation time")
def health(settings: SettingsDep, clock: ClockDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=settings.version,
        environment=settings.environment,
        virtual_clock_time=clock.now(),
    )
