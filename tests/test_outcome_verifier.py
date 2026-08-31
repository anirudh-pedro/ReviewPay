"""Outcome verification tests (Requirement 15.1-15.7, 25.12)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    CaseState,
    FailureReason,
    PaymentStatus,
    RiskLevel,
)
from app.models import RecoveryAction, RecoveryCase
from app.services.audit_service import AuditService
from app.services.outcome_verifier import OutcomeVerifier


@pytest.fixture
def verifier(db, clock) -> OutcomeVerifier:
    return OutcomeVerifier(session=db, clock=clock)


@pytest.fixture
def audit(db, clock) -> AuditService:
    return AuditService(session=db, clock=clock)


@pytest.fixture
def action_for(db, clock):
    """Persist a case plus an executed action against a payment."""
    counter = {"n": 0}

    def _make(payment, action_type: ActionType = ActionType.RETRY_LATER) -> RecoveryAction:
        counter["n"] += 1
        now = clock.now()
        case = RecoveryCase(
            case_id=f"case_ver_{counter['n']:04d}",
            payment_id=payment.payment_id,
            state=CaseState.VERIFYING,
            amount_at_risk=payment.amount,
            created_at=now,
            updated_at=now,
        )
        db.add(case)
        db.flush()

        record = RecoveryAction(
            action_id=f"act_ver_{counter['n']:04d}",
            case_id=case.case_id,
            payment_id=payment.payment_id,
            action_type=action_type,
            estimated_probability=0.776,
            confidence=1.0,
            model_version="deterministic-scorer-v1",
            expected_recovery_value=764_000,
            erv_breakdown={},
            risk_level=RiskLevel.LOW,
            decision_explanation={},
            status=ActionStatus.EXECUTED,
            created_at=now,
            executed_at=now,
        )
        db.add(record)
        db.commit()
        return record

    return _make


# ---------------------------------------------------------------------------
# Recovered path (Requirement 15.3)
# ---------------------------------------------------------------------------


def test_failed_to_succeeded_is_a_recovery(verifier, payment_factory, action_for, db, clock):
    """Requirement 15.3."""
    payment = payment_factory(amount=1_000_000, status=PaymentStatus.SUCCEEDED)
    action = action_for(payment)

    outcome = verifier.verify(action, PaymentStatus.FAILED)
    db.commit()

    assert outcome.recovered is True
    assert outcome.recovered_amount == 1_000_000
    assert outcome.previous_payment_status is PaymentStatus.FAILED
    assert outcome.new_payment_status is PaymentStatus.SUCCEEDED
    assert outcome.failure_reason is None
    assert outcome.verification_timestamp == clock.now()


def test_outcome_carries_every_required_field(verifier, payment_factory, action_for, db):
    """Requirement 15.1."""
    payment = payment_factory(status=PaymentStatus.SUCCEEDED)
    outcome = verifier.verify(action_for(payment), PaymentStatus.FAILED)
    db.commit()

    for field in (
        "action_id",
        "previous_payment_status",
        "new_payment_status",
        "recovered",
        "recovered_amount",
        "failure_reason",
        "verification_timestamp",
    ):
        assert hasattr(outcome, field)


def test_abandoned_to_succeeded_is_a_recovery(verifier, payment_factory, action_for, db):
    payment = payment_factory(status=PaymentStatus.SUCCEEDED)
    outcome = verifier.verify(action_for(payment), PaymentStatus.ABANDONED)
    db.commit()
    assert outcome.recovered is True


def test_recovered_amount_is_the_payment_amount_in_minor_units(
    verifier, payment_factory, action_for, db
):
    """Requirement 15.3."""
    payment = payment_factory(amount=4_999_00, status=PaymentStatus.SUCCEEDED)
    outcome = verifier.verify(action_for(payment), PaymentStatus.FAILED)
    db.commit()

    assert outcome.recovered_amount == 4_999_00
    assert isinstance(outcome.recovered_amount, int)


# ---------------------------------------------------------------------------
# Unrecovered path (Requirement 15.4)
# ---------------------------------------------------------------------------


def test_still_failed_is_not_a_recovery(verifier, payment_factory, action_for, db):
    """Requirement 15.4."""
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.INSUFFICIENT_FUNDS
    )
    outcome = verifier.verify(action_for(payment), PaymentStatus.FAILED)
    db.commit()

    assert outcome.recovered is False
    assert outcome.recovered_amount == 0
    assert outcome.failure_reason is FailureReason.INSUFFICIENT_FUNDS


def test_already_successful_payment_is_not_double_counted(
    verifier, payment_factory, action_for, db
):
    """A payment that was already captured cannot be recovered again."""
    payment = payment_factory(status=PaymentStatus.SUCCEEDED)
    outcome = verifier.verify(action_for(payment), PaymentStatus.SUCCEEDED)
    db.commit()

    assert outcome.recovered is False
    assert outcome.recovered_amount == 0


@pytest.mark.parametrize(
    "status", [PaymentStatus.FAILED, PaymentStatus.ABANDONED, PaymentStatus.PENDING]
)
def test_no_recovery_for_any_unsuccessful_end_state(
    verifier, payment_factory, action_for, db, status
):
    payment = payment_factory(status=status, failure_reason=FailureReason.BANK_TIMEOUT)
    outcome = verifier.verify(action_for(payment), PaymentStatus.FAILED)
    db.commit()

    assert outcome.recovered is False
    assert outcome.recovered_amount == 0


# ---------------------------------------------------------------------------
# Independence from the executor (Requirement 15.2, 15.5, 25.12)
# ---------------------------------------------------------------------------


def test_recovery_is_decided_from_payment_state_not_the_execution_result(
    verifier, payment_factory, action_for, db
):
    """Requirement 25.12: the critical honesty guarantee.

    The executor here would have reported SUCCEEDED, but the persisted payment is
    still FAILED. Verification reports no recovery.
    """
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT
    )
    action = action_for(payment)

    # Simulate an executor that claimed success without changing the payment.
    action.status = ActionStatus.EXECUTED

    outcome = verifier.verify(action, PaymentStatus.FAILED)
    db.commit()

    assert outcome.recovered is False
    assert outcome.recovered_amount == 0


def test_verifier_never_imports_the_executor():
    """Requirement 15.5: separate from execution, by construction."""
    path = Path(__file__).resolve().parents[1] / "app" / "services" / "outcome_verifier.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    assert not any("integrations" in module for module in modules)
    assert not any("simulator" in module for module in modules)


def test_verifier_exposes_no_execution_method():
    names = {name for name in dir(OutcomeVerifier) if not name.startswith("_")}
    assert names == {"verify"}


def test_missing_payment_raises(verifier, payment_factory, action_for, db):
    from app.core.errors import RecordNotFound

    payment = payment_factory(status=PaymentStatus.SUCCEEDED)
    action = action_for(payment)
    action.payment_id = "pay_vanished"
    db.commit()

    with pytest.raises(RecordNotFound):
        verifier.verify(action, PaymentStatus.FAILED)


# ---------------------------------------------------------------------------
# Audit (Requirement 15.6)
# ---------------------------------------------------------------------------


def test_recovery_records_verified_then_recovered(
    verifier, audit, payment_factory, action_for, db
):
    """Requirement 15.6."""
    payment = payment_factory(amount=1_000_000, status=PaymentStatus.SUCCEEDED)
    action = action_for(payment)

    verifier.verify(action, PaymentStatus.FAILED, audit=audit, workflow_id="wf_ver")
    db.commit()

    assert audit.event_types_for_case(action.case_id) == [
        AuditEventType.OUTCOME_VERIFIED,
        AuditEventType.REVENUE_RECOVERED,
    ]

    verified, recovered = audit.for_case(action.case_id)
    assert verified.meta["recovered"] is True
    assert verified.meta["previous_payment_status"] == "FAILED"
    assert verified.meta["new_payment_status"] == "SUCCEEDED"
    assert "not used" in verified.meta["verification_basis"]
    assert recovered.meta["recovered_amount"] == 1_000_000
    assert recovered.meta["expected_recovery_value"] == 764_000
    assert recovered.meta["model_version"] == "deterministic-scorer-v1"
    assert recovered.meta["workflow_id"] == "wf_ver"


def test_no_recovery_records_only_verified(verifier, audit, payment_factory, action_for, db):
    """Requirement 15.6: REVENUE_RECOVERED fires only on real recovery."""
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.INSUFFICIENT_FUNDS
    )
    action = action_for(payment)

    verifier.verify(action, PaymentStatus.FAILED, audit=audit)
    db.commit()

    assert audit.event_types_for_case(action.case_id) == [AuditEventType.OUTCOME_VERIFIED]
    assert AuditEventType.REVENUE_RECOVERED not in audit.event_types_for_case(action.case_id)


def test_verification_without_audit_still_persists_the_outcome(
    verifier, payment_factory, action_for, db
):
    payment = payment_factory(status=PaymentStatus.SUCCEEDED)
    outcome = verifier.verify(action_for(payment), PaymentStatus.FAILED)
    db.commit()

    from app.models import RecoveryOutcome

    assert db.get(RecoveryOutcome, outcome.outcome_id) is not None


def test_outcome_is_linked_to_its_action(verifier, payment_factory, action_for, db):
    payment = payment_factory(status=PaymentStatus.SUCCEEDED)
    action = action_for(payment)
    outcome = verifier.verify(action, PaymentStatus.FAILED)
    db.commit()

    db.refresh(action)
    assert action.outcome is not None
    assert action.outcome.outcome_id == outcome.outcome_id
    assert outcome.action.action_id == action.action_id
