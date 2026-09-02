"""Durable database-backed unit of background work."""

from __future__ import annotations
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdColumn
from app.db.integrity import (
    JOB_ATTEMPT_BOUNDS_CHECK,
    JOB_ATTEMPT_BOUNDS_PREDICATE,
    JOB_CASE_FOREIGN_KEY,
    JOB_STATUS_CHECK,
    JOB_STATUS_PREDICATE,
)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_claim", "status", "available_at", "lease_expires_at"),
        Index("ix_background_jobs_case_id", "case_id"),
        # The lifecycle is closed and the retry bound is enforced by the database,
        # not only by the service (Requirement 12.1, 12.7).
        CheckConstraint(JOB_STATUS_PREDICATE, name=JOB_STATUS_CHECK),
        CheckConstraint(JOB_ATTEMPT_BOUNDS_PREDICATE, name=JOB_ATTEMPT_BOUNDS_CHECK),
    )

    job_id: Mapped[str] = mapped_column(IdColumn, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Nullable: a job need not belong to a recovery case. When it does, the case
    # must exist (Requirement 10.6).
    case_id: Mapped[str | None] = mapped_column(
        IdColumn,
        ForeignKey("recovery_cases.case_id", name=JOB_CASE_FOREIGN_KEY),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
