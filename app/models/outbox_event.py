"""Transactional outbox record for operational events."""

from __future__ import annotations
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdColumn
from app.db.integrity import OUTBOX_ATTEMPTS_CHECK, OUTBOX_ATTEMPTS_PREDICATE


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_pending", "published_at", "created_at"),
        CheckConstraint(OUTBOX_ATTEMPTS_PREDICATE, name=OUTBOX_ATTEMPTS_CHECK),
    )
    # ``aggregate_id`` is deliberately not a foreign key: the outbox is
    # polymorphic over ``aggregate_type``, and a single-target foreign key would
    # be wrong for every non-``RecoveryCase`` aggregate. The delivery service owns
    # that relationship check (Requirement 10.6, 12.10).

    event_id: Mapped[str] = mapped_column(IdColumn, primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(IdColumn, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
