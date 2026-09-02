"""Persistent mapping between a RevivePay payment and a gateway order.

This model intentionally stores provider identifiers only. It never stores a raw
Checkout callback, webhook body, customer contact data, or payment instrument
information.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdColumn, ShortText

if TYPE_CHECKING:
    from app.models.payment import Payment


class GatewayPayment(Base):
    """The authoritative local mapping for one provider-backed checkout order."""

    __tablename__ = "gateway_payments"
    __table_args__ = (
        Index("ix_gateway_payments_provider_order_id", "provider_order_id"),
        Index("ix_gateway_payments_provider_payment_id", "provider_payment_id"),
    )

    gateway_payment_id: Mapped[str] = mapped_column(IdColumn, primary_key=True)
    provider: Mapped[str] = mapped_column(ShortText, nullable=False)
    payment_id: Mapped[str] = mapped_column(
        IdColumn, ForeignKey("payments.payment_id"), nullable=False, unique=True
    )
    provider_order_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    provider_status: Mapped[str | None] = mapped_column(ShortText, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    payment: Mapped["Payment"] = relationship(back_populates="gateway_payment")


__all__ = ["GatewayPayment"]
