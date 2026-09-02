"""Recovery case model.

The unit of recovery work: one at-risk payment tracked through the lifecycle. The
case owns the amount at risk, the current state, and the persisted diagnosis
(Requirement 2.4).

Permitted state transitions are enforced by ``app.services.state_machine``, not by
this model.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, text
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import CaseState
from app.db.base import Base, IdColumn, MoneyMinorUnits, enum_column
from app.db.integrity import OPEN_RECOVERY_CASE_INDEX, OPEN_RECOVERY_CASE_PREDICATE

if TYPE_CHECKING:
    from app.models.audit_event import AuditEvent
    from app.models.payment import Payment
    from app.models.recovery_action import RecoveryAction


class RecoveryCase(Base):
    """A recovery workflow tracking one at-risk payment."""

    __tablename__ = "recovery_cases"
    __table_args__ = (
        Index("ix_recovery_cases_payment_id", "payment_id"),
        Index("ix_recovery_cases_state", "state"),
        # At most one *open* case per payment. Filtered rather than plain so a
        # payment keeps its full history of terminal cases (Requirement 10.5).
        Index(
            OPEN_RECOVERY_CASE_INDEX,
            "payment_id",
            unique=True,
            sqlite_where=text(OPEN_RECOVERY_CASE_PREDICATE),
            postgresql_where=text(OPEN_RECOVERY_CASE_PREDICATE),
        ),
    )

    case_id: Mapped[str] = mapped_column(IdColumn, primary_key=True)
    payment_id: Mapped[str] = mapped_column(
        IdColumn, ForeignKey("payments.payment_id"), nullable=False
    )

    state: Mapped[CaseState] = mapped_column(
        enum_column(CaseState), default=CaseState.DETECTED, nullable=False
    )

    # Minor units. Captured at detection so analytics can report revenue at risk
    # even after the payment is later recovered.
    amount_at_risk: Mapped[int] = mapped_column(MoneyMinorUnits, nullable=False)

    # Structured diagnosis, written once the diagnosis engine runs.
    diagnosis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Summary written when the case reaches a terminal state.
    terminal_outcome: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    payment: Mapped["Payment"] = relationship(back_populates="recovery_cases")
    actions: Mapped[list["RecoveryAction"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="RecoveryAction.created_at",
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="AuditEvent.timestamp, AuditEvent.sequence",
    )

    @property
    def is_terminal(self) -> bool:
        """True when no further transition is permitted (Requirement 16.6)."""
        return self.state in CaseState.terminal()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<RecoveryCase {self.case_id} {self.state.value} "
            f"at_risk={self.amount_at_risk}>"
        )
