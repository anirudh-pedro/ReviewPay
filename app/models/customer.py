"""Customer model.

Carries the behavioural history that recovery scoring depends on: how often this
customer has paid successfully, what they typically spend, and whether they hold a
subscription (Requirement 2.3).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, Integer
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import SubscriptionStatus
from app.db.base import Base, IdColumn, MoneyMinorUnits, ShortText, enum_column

if TYPE_CHECKING:
    from app.models.payment import Payment


class Customer(Base):
    """A merchant's customer and their payment history."""

    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(IdColumn, primary_key=True)

    # --- Behavioural history (drives recovery scoring) ---
    historical_payment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_payment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_payment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    historical_success_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Minor units (paise for INR).
    average_transaction_value: Mapped[int] = mapped_column(
        MoneyMinorUnits, default=0, nullable=False
    )

    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        enum_column(SubscriptionStatus),
        default=SubscriptionStatus.NONE,
        nullable=False,
    )

    # Mapped as ``meta`` because ``metadata`` is reserved on declarative classes;
    # the database column is named ``metadata`` as specified.
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Every record produced by simulation or seeding is flagged synthetic so no
    # figure can be mistaken for a real payment result (Requirement 4.6, 21.8).
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    name: Mapped[str | None] = mapped_column(ShortText, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    payments: Mapped[list["Payment"]] = relationship(
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="Payment.created_at",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Customer {self.customer_id} "
            f"success_rate={self.historical_success_rate:.2f} "
            f"payments={self.historical_payment_count}>"
        )
