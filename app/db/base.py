"""SQLAlchemy declarative base and shared column helpers.

Two conventions apply across every model:

- **Money is an integer in minor units** (paise for INR). No float ever holds an
  amount (Requirement 2.8).
- **Timestamps are supplied by the caller from the virtual clock**, never by a
  database default or a wall-clock read. That is what keeps a seeded run
  byte-identical across machines (Requirement 27.2).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all RevivePay models."""


def new_id(prefix: str) -> str:
    """Generate a short prefixed identifier, e.g. ``pay_9f2c1a4b``.

    Seeded data uses explicit sequential identifiers instead, so that reseeding
    with the same seed reproduces the same rows (Requirement 21.3).
    """
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def enum_column(enum_cls: type, *, length: int = 40) -> SAEnum:
    """Persist an enumeration as a portable VARCHAR rather than a native DB enum.

    Keeps the SQLite schema simple and the PostgreSQL swap a configuration change
    (Requirement 27.10).
    """
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=length,
        validate_strings=True,
    )


# Column type aliases used by the models for intent-revealing declarations.
MoneyMinorUnits = Integer
IdColumn = String(64)
ShortText = String(255)
