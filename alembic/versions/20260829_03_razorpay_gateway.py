"""Add Razorpay gateway mappings and verified webhook delivery ledger.

Revision ID: 20260829_03
Revises: 20260829_02
"""

from alembic import op
import sqlalchemy as sa

revision = "20260829_03"
down_revision = "20260829_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_payments",
        sa.Column("gateway_payment_id", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(255), nullable=False),
        sa.Column("payment_id", sa.String(64), sa.ForeignKey("payments.payment_id"), nullable=False, unique=True),
        sa.Column("provider_order_id", sa.String(128), nullable=False, unique=True),
        sa.Column("provider_payment_id", sa.String(128), nullable=True, unique=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("provider_status", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_gateway_payments_provider_order_id", "gateway_payments", ["provider_order_id"])
    op.create_index("ix_gateway_payments_provider_payment_id", "gateway_payments", ["provider_payment_id"])
    op.create_table(
        "gateway_webhook_events",
        sa.Column("webhook_event_id", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(255), nullable=False),
        sa.Column("delivery_id", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("raw_payload_sha256", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(255), nullable=False),
        sa.Column("provider_order_id", sa.String(128), nullable=True),
        sa.Column("provider_payment_id", sa.String(128), nullable=True),
        sa.Column("processing_status", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_gateway_webhook_events_provider_order_id", "gateway_webhook_events", ["provider_order_id"])
    op.create_index("ix_gateway_webhook_events_provider_payment_id", "gateway_webhook_events", ["provider_payment_id"])


def downgrade() -> None:
    op.drop_table("gateway_webhook_events")
    op.drop_table("gateway_payments")
