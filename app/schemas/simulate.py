"""Virtual clock schemas (Requirement 24.4, 18.6)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class AdvanceClockRequest(BaseModel):
    """Advance simulation time.

    Time never moves on its own, so a demo advances it explicitly to make a
    scheduled ``RETRY_LATER`` become due.
    """

    minutes: int = Field(default=0, ge=0, examples=[15])
    hours: int = Field(default=0, ge=0, examples=[0])

    @model_validator(mode="after")
    def _require_some_movement(self) -> "AdvanceClockRequest":
        if self.minutes == 0 and self.hours == 0:
            raise ValueError("Specify a non-zero number of minutes or hours to advance.")
        return self


class ClockResponse(BaseModel):
    """The simulation time after the requested change."""

    virtual_clock_time: datetime
    advanced_by_minutes: int = 0
    previous_virtual_clock_time: datetime | None = None
