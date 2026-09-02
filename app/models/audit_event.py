"""Audit event model.

Append-only decision trail. Every row answers what happened, why, what initiated
it, what was decided, what the policy allowed, and what the outcome was
(Requirement 2.7, 19.2).

Written exclusively through ``app.services.audit_service.AuditService``; no other
component constructs rows of this table (Requirement 19.6). Metadata carries the
``workflow_id``, which is what makes a workflow run reconstructable from the
database without a separate table.

Instrument credentials and customer contact details are never recorded here
(Requirement 19.8).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AuditEventType, WorkflowStage
from app.db.base import Base, IdColumn, enum_column
from app.db.integrity import AUDIT_SEQUENCE_UNIQUE_INDEX, install_audit_immutability

if TYPE_CHECKING:
    from app.models.recovery_case import RecoveryCase


class AuditEvent(Base):
    """One immutable audit record."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_case_id", "case_id"),
        Index("ix_audit_events_payment_id", "payment_id"),
        Index("ix_audit_events_event_type", "event_type"),
        UniqueConstraint("case_id", "sequence", name=AUDIT_SEQUENCE_UNIQUE_INDEX),
    )

    event_id: Mapped[str] = mapped_column(IdColumn, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        IdColumn, ForeignKey("recovery_cases.case_id"), nullable=False
    )
    payment_id: Mapped[str] = mapped_column(IdColumn, nullable=False)

    stage: Mapped[WorkflowStage] = mapped_column(enum_column(WorkflowStage), nullable=False)
    event_type: Mapped[AuditEventType] = mapped_column(
        enum_column(AuditEventType, length=64), nullable=False
    )

    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Monotonic per-case ordering key. Simulation time does not advance between
    # the stages of a single run, so several events legitimately share one
    # timestamp; this preserves their true order (Requirement 19.7).
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ``metadata`` column; attribute renamed because the name is reserved on
    # declarative classes. Carries workflow_id, model_version, probability,
    # confidence, expected recovery value, alternatives, explanation, and the
    # deciding policy rule where applicable (Requirement 19.3, 19.4).
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Simulation time, from the virtual clock.
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    case: Mapped["RecoveryCase"] = relationship(back_populates="audit_events")

    @property
    def workflow_id(self) -> str | None:
        """The workflow run that produced this event, if any."""
        return (self.meta or {}).get("workflow_id")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<AuditEvent {self.event_type.value} case={self.case_id} "
            f"stage={self.stage.value} at={self.timestamp.isoformat()}>"
        )


# Append-only at the persistence boundary, not only by convention: the database
# itself refuses to update a recorded event (Requirement 10.7, 10.8).
install_audit_immutability(AuditEvent.__table__)
