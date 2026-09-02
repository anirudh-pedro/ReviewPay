"""Payment attempt model.

One row per charge attempt, whether it came from the original checkout or from a
recovery action. ``action_type`` records which recovery action produced the
attempt, which is how the context builder reconstructs what has already been
tried and how the failure provenance is carried (Requirement 4.3).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ActionType, FailureReason, PaymentStatus
from app.db.base import Base, IdColumn, ShortText, enum_column
from app.db.integrity import (
    PAYMENT_ATTEMPT_NUMBER_CHECK,
    PAYMENT_ATTEMPT_NUMBER_PREDICATE,
    PAYMENT_ATTEMPT_UNIQUE_INDEX,
)

if TYPE_CHECKING:
    from app.models.payment import Payment


class PaymentAttempt(Base):
    """A single attempt to charge a payment."""

    __tablename__ = "payment_attempts"
    __table_args__ = (
        Index("ix_payment_attempts_payment_id", "payment_id"),
        # ``(payment_id, attempt_number)`` is the authoritative attempt key: the
        # attempt number is the payment's own attempt counter, so a duplicate
        # would mean two rows claiming the same try (Requirement 10.5).
        Index(
            PAYMENT_ATTEMPT_UNIQUE_INDEX, "payment_id", "attempt_number", unique=True
        ),
        CheckConstraint(
            PAYMENT_ATTEMPT_NUMBER_PREDICATE, name=PAYMENT_ATTEMPT_NUMBER_CHECK
        ),
    )

    attempt_id: Mapped[str] = mapped_column(IdColumn, primary_key=True)
    payment_id: Mapped[str] = mapped_column(
        IdColumn, ForeignKey("payments.payment_id"), nullable=False
    )

    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(enum_column(PaymentStatus), nullable=False)
    failure_reason: Mapped[FailureReason | None] = mapped_column(
        enum_column(FailureReason), nullable=True
    )

    # Set when this attempt was produced by a recovery action rather than by the
    # original checkout.
    action_type: Mapped[ActionType | None] = mapped_column(
        enum_column(ActionType), nullable=True
    )

    # Simulated provider payload. Contains no instrument credentials
    # (Requirement 19.8).
    provider_response: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    # Where the attempt originated: checkout, subscription charge, or recovery.
    source: Mapped[str] = mapped_column(ShortText, default="checkout", nullable=False)

    attempted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    payment: Mapped["Payment"] = relationship(back_populates="attempts")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<PaymentAttempt {self.attempt_id} #{self.attempt_number} "
            f"{self.status.value} action={self.action_type.value if self.action_type else None}>"
        )
