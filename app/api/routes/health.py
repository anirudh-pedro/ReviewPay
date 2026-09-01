"""Public liveness and database-readiness probes."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import ClockDep, SessionDep, SettingsDep
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service liveness and simulation time")
def health(settings: SettingsDep, clock: ClockDep) -> HealthResponse:
    return HealthResponse(status="ok", app_name=settings.app_name, version=settings.version, environment=settings.environment, virtual_clock_time=clock.now())


@router.get("/readyz", summary="Database readiness")
def readyz(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ready", "database": "reachable"}
