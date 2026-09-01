"""Virtual-clock read and protected control endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.auth import OperationsPrincipalDep
from app.api.deps import ClockDep
from app.schemas.simulate import AdvanceClockRequest, ClockResponse

router = APIRouter(prefix="/simulate", tags=["simulation"])


@router.post("/advance-clock", response_model=ClockResponse, summary="Advance simulation time")
def advance_clock(request: AdvanceClockRequest, clock: ClockDep, _: OperationsPrincipalDep) -> ClockResponse:
    previous = clock.now()
    current = clock.advance(minutes=request.minutes, hours=request.hours)
    return ClockResponse(virtual_clock_time=current, advanced_by_minutes=request.minutes + request.hours * 60, previous_virtual_clock_time=previous)


@router.get("/clock", response_model=ClockResponse, summary="Read simulation time")
def read_clock(clock: ClockDep) -> ClockResponse:
    return ClockResponse(virtual_clock_time=clock.now())
