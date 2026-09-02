"""FastAPI dependency composition and bounded request helpers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings, get_settings
from app.core.container import get_clock
from app.integrations.razorpay import RazorpayGateway, RazorpayHttpClient
from app.db.session import get_session


def settings_dep() -> Settings:
    return get_settings()


def clock_dep(settings: Annotated[Settings, Depends(settings_dep)]) -> VirtualClock:
    return get_clock(settings)


def razorpay_client_dep(settings: Annotated[Settings, Depends(settings_dep)]) -> RazorpayGateway:
    """Construct the narrow Razorpay adapter; tests override this dependency."""
    return RazorpayHttpClient(settings)


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
ClockDep = Annotated[VirtualClock, Depends(clock_dep)]
RazorpayClientDep = Annotated[RazorpayGateway, Depends(razorpay_client_dep)]


class Pagination:
    """Shared, intentionally bounded list pagination parameters."""

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=100, description="Maximum records to return (hard limit: 100).")] = 50,
        offset: Annotated[int, Query(ge=0, le=10_000, description="Records to skip (hard limit: 10,000).")] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


PaginationDep = Annotated[Pagination, Depends(Pagination)]
