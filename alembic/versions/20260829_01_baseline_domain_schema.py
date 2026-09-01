"""Baseline the established seven-domain-table RevivePay schema.

Revision ID: 20260829_01
Revises: None
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.core.enums import (
    ActionStatus, ActionType, AuditEventType, CaseState, FailureReason,
    PaymentMethod, PaymentStatus, PolicyOutcome, RiskLevel, SubscriptionStatus,
    WorkflowStage,
)

revision = "20260829_01"
down_revision = None
branch_labels = None
depends_on = None


def _enum(enum_cls: type, length: int = 40) -> sa.Enum:
    return sa.Enum(enum_cls, native_enum=False, length=length, validate_strings=True)


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.String(length=64), primary_key=True),
        sa.Column("historical_payment_count", sa.Integer(), nullable=False),
        sa.Column("successful_payment_count", sa.Integer(), nullable=False),
        sa.Column("failed_payment_count", sa.Integer(), nullable=False),
        sa.Column("historical_success_rate", sa.Float(), nullable=False),
        sa.Column("average_transaction_value", sa.Integer(), nullable=False),
        sa.Column("subscription_status", _enum(SubscriptionStatus), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "payments",
        sa.Column("payment_id", sa.String(length=64), primary_key=True),
        sa.Column("customer_id", sa.String(length=64), sa.ForeignKey("customers.customer_id"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=255), nullable=False),
        sa.Column("payment_method", _enum(PaymentMethod), nullable=False),
        sa.Column("status", _enum(PaymentStatus), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("failure_reason", _enum(FailureReason), nullable=True),
        sa.Column("merchant_id", sa.String(length=64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_payments_customer_id", "payments", ["customer_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_table(
        "payment_attempts",
        sa.Column("attempt_id", sa.String(length=64), primary_key=True),
        sa.Column("payment_id", sa.String(length=64), sa.ForeignKey("payments.payment_id"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", _enum(PaymentStatus), nullable=False),
        sa.Column("failure_reason", _enum(FailureReason), nullable=True),
        sa.Column("action_type", _enum(ActionType), nullable=True),
        sa.Column("provider_response", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_payment_attempts_payment_id", "payment_attempts", ["payment_id"])
    op.create_table(
        "recovery_cases",
        sa.Column("case_id", sa.String(length=64), primary_key=True),
        sa.Column("payment_id", sa.String(length=64), sa.ForeignKey("payments.payment_id"), nullable=False),
        sa.Column("state", _enum(CaseState), nullable=False),
        sa.Column("amount_at_risk", sa.Integer(), nullable=False),
        sa.Column("diagnosis", sa.JSON(), nullable=True),
        sa.Column("terminal_outcome", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_recovery_cases_payment_id", "recovery_cases", ["payment_id"])
    op.create_index("ix_recovery_cases_state", "recovery_cases", ["state"])
    op.create_table(
        "recovery_actions",
        sa.Column("action_id", sa.String(length=64), primary_key=True),
        sa.Column("case_id", sa.String(length=64), sa.ForeignKey("recovery_cases.case_id"), nullable=False),
        sa.Column("payment_id", sa.String(length=64), nullable=False),
        sa.Column("action_type", _enum(ActionType), nullable=False),
        sa.Column("estimated_probability", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(length=255), nullable=False),
        sa.Column("expected_recovery_value", sa.Integer(), nullable=False),
        sa.Column("erv_breakdown", sa.JSON(), nullable=False),
        sa.Column("risk_level", _enum(RiskLevel), nullable=False),
        sa.Column("decision_explanation", sa.JSON(), nullable=False),
        sa.Column("policy_outcome", _enum(PolicyOutcome), nullable=True),
        sa.Column("policy_rule_id", sa.String(length=255), nullable=True),
        sa.Column("policy_reason", sa.Text(), nullable=True),
        sa.Column("status", _enum(ActionStatus), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_recovery_actions_case_id", "recovery_actions", ["case_id"])
    op.create_index("ix_recovery_actions_payment_id", "recovery_actions", ["payment_id"])
    op.create_index("ix_recovery_actions_action_type", "recovery_actions", ["action_type"])
    op.create_table(
        "recovery_outcomes",
        sa.Column("outcome_id", sa.String(length=64), primary_key=True),
        sa.Column("action_id", sa.String(length=64), sa.ForeignKey("recovery_actions.action_id"), nullable=False, unique=True),
        sa.Column("previous_payment_status", _enum(PaymentStatus), nullable=False),
        sa.Column("new_payment_status", _enum(PaymentStatus), nullable=False),
        sa.Column("recovered", sa.Boolean(), nullable=False),
        sa.Column("recovered_amount", sa.Integer(), nullable=False),
        sa.Column("failure_reason", _enum(FailureReason), nullable=True),
        sa.Column("verification_timestamp", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_recovery_outcomes_action_id", "recovery_outcomes", ["action_id"])
    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("case_id", sa.String(length=64), sa.ForeignKey("recovery_cases.case_id"), nullable=False),
        sa.Column("payment_id", sa.String(length=64), nullable=False),
        sa.Column("stage", _enum(WorkflowStage), nullable=False),
        sa.Column("event_type", _enum(AuditEventType, 64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_events_case_id", "audit_events", ["case_id"])
    op.create_index("ix_audit_events_payment_id", "audit_events", ["payment_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])


def downgrade() -> None:
    for table in (
        "audit_events", "recovery_outcomes", "recovery_actions", "recovery_cases",
        "payment_attempts", "payments", "customers",
    ):
        op.drop_table(table)
