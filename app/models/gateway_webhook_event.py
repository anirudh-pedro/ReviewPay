"""Inbound gateway webhook delivery ledger.

Only a SHA-256 digest of the raw delivery is retained. This gives duplicate
protection and auditability without retaining unbounded provider payloads or
sensitive callback fields.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdColumn, ShortText


class GatewayWebhookEvent(Base):
    """One verified inbound provider delivery, recorded exactly once."""

    __tablename__ = "gateway_webhook_events"
    __table_args__ = (
        Index("ix_gateway_webhook_events_provider_order_id", "provider_order_id"),
        Index("ix_gateway_webhook_events_provider_payment_id", "provider_payment_id"),
    )

    webhook_event_id: Mapped[str] = mapped_column(IdColumn, primary_key=True)
    provider: Mapped[str] = mapped_column(ShortText, nullable=False)
    delivery_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    raw_payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(ShortText, nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processing_status: Mapped[str] = mapped_column(ShortText, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


__all__ = ["GatewayWebhookEvent"]
