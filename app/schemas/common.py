"""Shared response schemas.

Two conventions hold across every endpoint:

- **Money is an integer in minor units plus a currency code** (Requirement 24.7).
  No endpoint returns a float amount.
- **Every analytics or report payload is labelled synthetic** so no figure can be
  mistaken for a real payment result (Requirement 20.5, 27.1).

Schemas import no SQLAlchemy model; they describe the wire format only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

#: Marker attached to every computed-metric payload.
SYNTHETIC_DATA_SOURCE = "synthetic_simulation"

SYNTHETIC_DATA_NOTICE = (
    "All figures are the result of a deterministic synthetic simulation. "
    "No real payment was processed and no real money moved."
)


class ErrorDetail(BaseModel):
    """Machine-readable code plus a human-readable message."""

    code: str = Field(examples=["NOT_FOUND"])
    message: str = Field(examples=["Recovery case 'case_0001' was not found."])


class ErrorResponse(BaseModel):
    """The standard error envelope (Requirement 1.8)."""

    error: ErrorDetail


class Money(BaseModel):
    """An amount in minor units with its currency code."""

    model_config = ConfigDict(from_attributes=True)

    amount: int = Field(description="Amount in minor units (paise for INR).", examples=[1_000_000])
    currency: str = Field(default="INR", examples=["INR"])

    @classmethod
    def of(cls, amount: int, currency: str = "INR") -> "Money":
        return cls(amount=int(amount), currency=currency)


class Page(BaseModel, Generic[T]):
    """A paginated collection."""

    items: list[T]
    total: int = Field(description="Total matching records.")
    limit: int
    offset: int


class HealthResponse(BaseModel):
    """Service health and the current simulation time (Requirement 24.1)."""

    status: str = Field(default="ok")
    app_name: str
    version: str
    environment: str
    virtual_clock_time: datetime = Field(
        description="Current simulation time. Advances only via /simulate/advance-clock."
    )
    data_source: str = Field(default=SYNTHETIC_DATA_SOURCE)


class SyntheticNotice(BaseModel):
    """Mixin-style provenance block for computed payloads."""

    data_source: str = Field(default=SYNTHETIC_DATA_SOURCE)
    notice: str = Field(default=SYNTHETIC_DATA_NOTICE)
