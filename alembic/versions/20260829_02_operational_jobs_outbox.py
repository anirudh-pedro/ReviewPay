"""Add durable jobs, outbox records, and database audit ordering.

Revision ID: 20260829_02
Revises: 20260829_01
"""

from alembic import op
import sqlalchemy as sa

revision = "20260829_02"
down_revision = "20260829_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A unique index is portable to SQLite and enforces per-case audit ordering.
    op.create_index("uq_audit_events_case_sequence", "audit_events", ["case_id", "sequence"], unique=True)
    op.create_table(
        "background_jobs",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("last_error", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_background_jobs_claim", "background_jobs", ["status", "available_at", "lease_expires_at"])
    op.create_index("ix_background_jobs_case_id", "background_jobs", ["case_id"])
    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_outbox_events_pending", "outbox_events", ["published_at", "created_at"])


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("background_jobs")
    op.drop_index("uq_audit_events_case_sequence", table_name="audit_events")
