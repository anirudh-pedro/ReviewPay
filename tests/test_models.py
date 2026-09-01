"""Domain model and persistence tests (Requirement 2.1-2.12)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    CaseState,
    FailureReason,
    PaymentStatus,
    PolicyOutcome,
    RiskLevel,
    WorkflowStage,
)
from app.db.base import Base
from app.models import (
    ALL_MODELS,
    LEGACY_DOMAIN_MODELS,
    AuditEvent,
    PaymentAttempt,
    RecoveryAction,
    RecoveryCase,
    RecoveryOutcome,
)

EXPECTED_TABLES = {
    "customers",
    "payments",
    "payment_attempts",
    "recovery_cases",
    "recovery_actions",
    "recovery_outcomes",
    "audit_events",
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_legacy_domain_models_remain_declared():
    """P4 preserves the original seven recovery-domain models."""
    assert len(LEGACY_DOMAIN_MODELS) == 7
    assert len(ALL_MODELS) == 9


def test_baseline_migration_creates_the_legacy_domain_schema(tmp_path):
    """P4.1: a fresh SQLite database upgrades through an auditable revision."""
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "schema.db"
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}", future=True)
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_alembic_configuration_and_fixed_baseline_exist():
    """P4.1: migrations are an explicit, reviewable production contract."""
    root = Path(__file__).resolve().parents[1]
    assert (root / "alembic.ini").is_file()
    assert (root / "alembic" / "env.py").is_file()
    assert (root / "alembic" / "versions" / "20260829_01_baseline_domain_schema.py").is_file()
    assert (root / "alembic" / "versions" / "20260829_02_operational_jobs_outbox.py").is_file()


def test_declared_indexes_are_created(db_engine):
    """Requirement 2.10."""
    inspector = inspect(db_engine)

    def index_columns(table: str) -> set[str]:
        return {
            column
            for index in inspector.get_indexes(table)
            for column in index["column_names"]
            if column
        }

    assert "customer_id" in index_columns("payments")
    assert "status" in index_columns("payments")
    assert "payment_id" in index_columns("recovery_cases")
    assert "state" in index_columns("recovery_cases")
    assert "case_id" in index_columns("recovery_actions")
    assert "case_id" in index_columns("audit_events")


def test_metadata_column_is_named_metadata(db_engine):
    """The attribute is ``meta`` (``metadata`` is reserved); the column is not."""
    columns = {column["name"] for column in inspect(db_engine).get_columns("payments")}
    assert "metadata" in columns


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


def test_money_columns_are_integers(db_engine):
    """Requirement 2.8: money is never a float."""
    inspector = inspect(db_engine)

    money_columns = {
        "payments": ["amount"],
        "customers": ["average_transaction_value"],
        "recovery_cases": ["amount_at_risk"],
        "recovery_actions": ["expected_recovery_value"],
        "recovery_outcomes": ["recovered_amount"],
    }

    for table, names in money_columns.items():
        types = {column["name"]: str(column["type"]).upper() for column in inspector.get_columns(table)}
        for name in names:
            assert "INT" in types[name], f"{table}.{name} must be an integer column"


def test_currency_defaults_to_inr(payment_factory):
    """Requirement 2.8."""
    assert payment_factory().currency == "INR"


def test_amounts_round_trip_as_minor_units(payment_factory, db):
    payment = payment_factory(amount=1_000_000)  # INR 10,000.00
    db.refresh(payment)
    assert payment.amount == 1_000_000
    assert isinstance(payment.amount, int)


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------


def test_customer_to_payment_relationship(db, customer_factory, payment_factory):
    """Requirement 2.9."""
    customer = customer_factory()
    payment = payment_factory(customer=customer)

    db.refresh(customer)
    assert [item.payment_id for item in customer.payments] == [payment.payment_id]
    assert payment.customer.customer_id == customer.customer_id


def test_payment_to_attempt_relationship(db, payment_factory, clock):
    """Requirement 2.9."""
    payment = payment_factory()
    attempt = PaymentAttempt(
        attempt_id="att_0001",
        payment_id=payment.payment_id,
        attempt_number=1,
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.BANK_TIMEOUT,
        provider_response={"simulated": True},
        source="checkout",
        attempted_at=clock.now(),
    )
    db.add(attempt)
    db.commit()

    db.refresh(payment)
    assert [item.attempt_id for item in payment.attempts] == ["att_0001"]
    assert attempt.payment.payment_id == payment.payment_id


def test_case_action_outcome_chain(db, payment_factory, clock):
    """Requirement 2.9: RecoveryCase -> RecoveryAction -> RecoveryOutcome."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    now = clock.now()

    case = RecoveryCase(
        case_id="case_0001",
        payment_id=payment.payment_id,
        state=CaseState.DETECTED,
        amount_at_risk=payment.amount,
        created_at=now,
        updated_at=now,
    )
    db.add(case)
    db.commit()

    action = RecoveryAction(
        action_id="act_0001",
        case_id=case.case_id,
        payment_id=payment.payment_id,
        action_type=ActionType.RETRY_LATER,
        estimated_probability=0.776,
        confidence=1.0,
        model_version="deterministic-scorer-v1",
        expected_recovery_value=764_000,
        erv_breakdown={"gross_expected_recovery": 776_000},
        risk_level=RiskLevel.LOW,
        decision_explanation={"selected_action": "RETRY_LATER", "alternatives": []},
        policy_outcome=PolicyOutcome.APPROVED,
        policy_rule_id="default_approve",
        policy_reason="No blocking rule matched.",
        status=ActionStatus.APPROVED,
        created_at=now,
    )
    db.add(action)
    db.commit()

    outcome = RecoveryOutcome(
        outcome_id="out_0001",
        action_id=action.action_id,
        previous_payment_status=PaymentStatus.FAILED,
        new_payment_status=PaymentStatus.SUCCEEDED,
        recovered=True,
        recovered_amount=payment.amount,
        verification_timestamp=now,
    )
    db.add(outcome)
    db.commit()

    db.refresh(case)
    assert [item.action_id for item in case.actions] == ["act_0001"]
    assert case.actions[0].outcome.recovered is True
    assert case.actions[0].outcome.recovered_amount == payment.amount
    assert outcome.action.case.case_id == case.case_id


def test_case_to_audit_event_relationship(db, payment_factory, clock):
    """Requirement 2.9."""
    payment = payment_factory(status=PaymentStatus.FAILED)
    now = clock.now()
    case = RecoveryCase(
        case_id="case_0002",
        payment_id=payment.payment_id,
        state=CaseState.DETECTED,
        amount_at_risk=payment.amount,
        created_at=now,
        updated_at=now,
    )
    db.add(case)
    db.commit()

    event = AuditEvent(
        event_id="evt_0001",
        case_id=case.case_id,
        payment_id=payment.payment_id,
        stage=WorkflowStage.DETECTION,
        event_type=AuditEventType.REVENUE_RISK_DETECTED,
        message="Revenue at risk detected.",
        meta={"workflow_id": "wf_0001", "amount_at_risk": payment.amount},
        timestamp=now,
    )
    db.add(event)
    db.commit()

    db.refresh(case)
    assert [item.event_id for item in case.audit_events] == ["evt_0001"]
    assert case.audit_events[0].workflow_id == "wf_0001"


# ---------------------------------------------------------------------------
# Behaviour helpers
# ---------------------------------------------------------------------------


def test_payment_status_helpers(payment_factory):
    succeeded = payment_factory(status=PaymentStatus.SUCCEEDED)
    failed = payment_factory(status=PaymentStatus.FAILED)

    assert succeeded.is_successful is True
    assert succeeded.is_at_risk_status is False
    assert failed.is_successful is False
    assert failed.is_at_risk_status is True


def test_case_is_terminal_helper(db, payment_factory, clock):
    """Requirement 16.6."""
    payment = payment_factory()
    now = clock.now()
    case = RecoveryCase(
        case_id="case_0003",
        payment_id=payment.payment_id,
        state=CaseState.RECOVERED,
        amount_at_risk=payment.amount,
        created_at=now,
        updated_at=now,
    )
    db.add(case)
    db.commit()
    assert case.is_terminal is True

    case.state = CaseState.FAILED
    assert case.is_terminal is False


def test_timestamps_come_from_the_supplied_clock(payment_factory, clock):
    """Requirement 27.2: no wall-clock defaults anywhere in the schema."""
    payment = payment_factory()
    assert payment.created_at == clock.now()
    assert payment.created_at == datetime(2026, 1, 1, 13, 0, 0)


def test_synthetic_flag_defaults_true(payment_factory, customer_factory):
    """Requirement 4.6, 21.8."""
    assert payment_factory().is_synthetic is True
    assert customer_factory().is_synthetic is True
