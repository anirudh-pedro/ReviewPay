"""Payment model.

One unified payment record covers every revenue-at-risk channel. Checkout
abandonment and subscription failure are ``FailureReason`` values here rather than
separate entities, so a single detector and a single workflow serve all of them
(Requirement 2.2, 4.3).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import FailureReason, PaymentMethod, PaymentStatus
from app.db.base import Base, IdColumn, MoneyMinorUnits, ShortText, enum_column

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.gateway_payment import GatewayPayment
    from app.models.payment_attempt import PaymentAttempt
    from app.models.recovery_case import RecoveryCase


class Payment(Base):
    """A payment whose revenue may be at risk."""

    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_customer_id", "customer_id"),
        Index("ix_payments_status", "status"),
    )

    payment_id: Mapped[str] = mapped_column(IdColumn, primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        IdColumn, ForeignKey("customers.customer_id"), nullable=False
    )

    # Minor units (paise for INR). Never a float.
    amount: Mapped[int] = mapped_column(MoneyMinorUnits, nullable=False)
    currency: Mapped[str] = mapped_column(ShortText, default="INR", nullable=False)

    payment_method: Mapped[PaymentMethod] = mapped_column(
        enum_column(PaymentMethod), nullable=False
    )
    status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus), default=PaymentStatus.CREATED, nullable=False
    )

    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_reason: Mapped[FailureReason | None] = mapped_column(
        enum_column(FailureReason), nullable=True
    )

    merchant_id: Mapped[str] = mapped_column(IdColumn, nullable=False)

    # ``metadata`` column; attribute renamed because the name is reserved.
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    customer: Mapped["Customer"] = relationship(back_populates="payments")
    attempts: Mapped[list["PaymentAttempt"]] = relationship(
        back_populates="payment",
        cascade="all, delete-orphan",
        order_by="PaymentAttempt.attempt_number",
    )
    gateway_payment: Mapped["GatewayPayment | None"] = relationship(
        back_populates="payment", uselist=False, cascade="all, delete-orphan"
    )
    recovery_cases: Mapped[list["RecoveryCase"]] = relationship(
        back_populates="payment",
        cascade="all, delete-orphan",
        order_by="RecoveryCase.created_at",
    )

    @property
    def is_successful(self) -> bool:
        """True when this payment represents captured revenue."""
        return self.status in PaymentStatus.successful()

    @property
    def is_at_risk_status(self) -> bool:
        """True when this payment's status puts revenue at risk."""
        return self.status in PaymentStatus.unsuccessful()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Payment {self.payment_id} {self.amount} {self.currency} "
            f"{self.status.value} reason={self.failure_reason.value if self.failure_reason else None}>"
        )
