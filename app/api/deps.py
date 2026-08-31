"""FastAPI dependencies.

Route handlers receive fully constructed collaborators from here, which keeps the
handlers themselves limited to validation, delegation, and serialization
(Requirement 1.9).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings, get_settings
from app.core.container import get_clock
from app.db.session import get_session


def settings_dep() -> Settings:
    return get_settings()


def clock_dep(settings: Annotated[Settings, Depends(settings_dep)]) -> VirtualClock:
    return get_clock(settings)


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
ClockDep = Annotated[VirtualClock, Depends(clock_dep)]


class Pagination:
    """Shared list pagination parameters."""

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=200, description="Maximum records to return.")] = 50,
        offset: Annotated[int, Query(ge=0, description="Records to skip.")] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


PaginationDep = Annotated[Pagination, Depends(Pagination)]
