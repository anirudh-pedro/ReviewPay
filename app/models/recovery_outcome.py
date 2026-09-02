"""Recovery outcome model.

The verified result of an executed action. ``recovered`` is decided by re-reading
persisted payment state, never by trusting what the executor reported, which is
what makes the recovered-revenue figure defensible (Requirement 2.6, 15.2).

Analytics sums recovered revenue from these rows only (Requirement 15.7).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import FailureReason, PaymentStatus
from app.db.base import Base, IdColumn, MoneyMinorUnits, enum_column
from app.db.integrity import (
    RECOVERY_OUTCOME_AMOUNT_CHECK,
    RECOVERY_OUTCOME_AMOUNT_PREDICATE,
)

if TYPE_CHECKING:
    from app.models.recovery_action import RecoveryAction


class RecoveryOutcome(Base):
    """Independently verified outcome of one recovery action."""

    __tablename__ = "recovery_outcomes"
    __table_args__ = (
        Index("ix_recovery_outcomes_action_id", "action_id"),
        CheckConstraint(
            RECOVERY_OUTCOME_AMOUNT_PREDICATE, name=RECOVERY_OUTCOME_AMOUNT_CHECK
        ),
    )

    outcome_id: Mapped[str] = mapped_column(IdColumn, primary_key=True)
    action_id: Mapped[str] = mapped_column(
        IdColumn, ForeignKey("recovery_actions.action_id"), nullable=False, unique=True
    )

    previous_payment_status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus), nullable=False
    )
    new_payment_status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus), nullable=False
    )

    recovered: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Minor units. Zero whenever ``recovered`` is false (Requirement 15.4).
    recovered_amount: Mapped[int] = mapped_column(MoneyMinorUnits, default=0, nullable=False)

    failure_reason: Mapped[FailureReason | None] = mapped_column(
        enum_column(FailureReason), nullable=True
    )

    verification_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    action: Mapped["RecoveryAction"] = relationship(back_populates="outcome")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<RecoveryOutcome {self.outcome_id} recovered={self.recovered} "
            f"amount={self.recovered_amount} "
            f"{self.previous_payment_status.value}->{self.new_payment_status.value}>"
        )
