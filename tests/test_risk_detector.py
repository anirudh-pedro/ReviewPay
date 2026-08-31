"""Risk detection tests (Requirement 5.1-5.5)."""

from __future__ import annotations

import pytest

from app.core.enums import AuditEventType, CaseState, FailureReason, PaymentStatus
from app.services.audit_service import AuditService
from app.services.risk_detector import RiskDetector


@pytest.fixture
def detector(db, clock) -> RiskDetector:
    return RiskDetector(session=db, clock=clock, audit=AuditService(session=db, clock=clock))


@pytest.fixture
def audit(db, clock) -> AuditService:
    return AuditService(session=db, clock=clock)


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        FailureReason.BANK_TIMEOUT,
        FailureReason.INSUFFICIENT_FUNDS,
        FailureReason.EXPIRED_CARD,
        FailureReason.NETWORK_ERROR,
        FailureReason.CHECKOUT_ABANDONMENT,
        FailureReason.SUBSCRIPTION_FAILURE,
        FailureReason.UNKNOWN,
    ],
)
def test_one_detection_path_serves_every_failure_reason(detector, payment_factory, reason):
    """Requirement 5.1."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=reason, amount=750_000)
    assessment = detector.assess(payment)

    assert assessment.at_risk is True
    assert assessment.amount_at_risk == 750_000
    assert assessment.failure_reason is reason


def test_successful_payment_is_not_at_risk(detector, payment_factory):
    """Requirement 5.5."""
    payment = payment_factory(status=PaymentStatus.SUCCEEDED)
    assessment = detector.assess(payment)

    assert assessment.at_risk is False
    assert assessment.amount_at_risk == 0
    assert "SUCCEEDED" in assessment.reason
    assert "nothing to recover" in assessment.reason


def test_pending_payment_is_not_yet_at_risk(detector, payment_factory):
    payment = payment_factory(status=PaymentStatus.PENDING)
    assessment = detector.assess(payment)
    assert assessment.at_risk is False
    assert "not yet" in assessment.reason


def test_abandoned_payment_is_at_risk(detector, payment_factory):
    """Checkout abandonment travels the same path as a hard failure."""
    payment = payment_factory(
        status=PaymentStatus.ABANDONED, failure_reason=FailureReason.CHECKOUT_ABANDONMENT
    )
    assert detector.assess(payment).at_risk is True


def test_missing_failure_reason_resolves_to_unknown(detector, payment_factory):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=None)
    assessment = detector.assess(payment)

    assert assessment.at_risk is True
    assert assessment.failure_reason is FailureReason.UNKNOWN


def test_assessment_is_immutable(detector, payment_factory):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    assessment = detector.assess(payment)
    with pytest.raises(Exception):
        assessment.at_risk = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Case creation
# ---------------------------------------------------------------------------


def test_case_is_opened_in_detected_state_with_amount_at_risk(detector, payment_factory, db):
    """Requirement 5.2."""
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT, amount=1_000_000
    )
    case = detector.detect_and_open_case(payment)
    db.commit()

    assert case is not None
    assert case.state is CaseState.DETECTED
    assert case.amount_at_risk == 1_000_000
    assert case.payment_id == payment.payment_id
    assert case.diagnosis is None


def test_no_case_is_opened_for_a_successful_payment(detector, payment_factory):
    """Requirement 5.5."""
    payment = payment_factory(status=PaymentStatus.SUCCEEDED)
    assert detector.detect_and_open_case(payment) is None


def test_open_case_is_reused_rather_than_duplicated(detector, payment_factory, db):
    """Requirement 5.3."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)

    first = detector.detect_and_open_case(payment)
    db.commit()
    second = detector.detect_and_open_case(payment)
    db.commit()

    assert first is not None and second is not None
    assert first.case_id == second.case_id
    db.refresh(payment)
    assert len(payment.recovery_cases) == 1


def test_a_terminal_case_does_not_block_a_new_one(detector, payment_factory, db):
    """A recovered payment that fails again earns a fresh case."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)

    first = detector.detect_and_open_case(payment)
    db.commit()
    first.state = CaseState.STOPPED
    db.commit()

    second = detector.detect_and_open_case(payment)
    db.commit()

    assert second is not None
    assert second.case_id != first.case_id


def test_find_open_case_ignores_terminal_cases(detector, payment_factory, db):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    case = detector.detect_and_open_case(payment)
    db.commit()

    assert detector.find_open_case(payment.payment_id) is not None

    case.state = CaseState.RECOVERED
    db.commit()
    assert detector.find_open_case(payment.payment_id) is None


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def test_detection_records_exactly_one_audit_event(detector, audit, payment_factory, db):
    """Requirement 5.4."""
    payment = payment_factory(
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS,
        amount=250_000,
    )
    case = detector.detect_and_open_case(payment)
    db.commit()

    events = audit.for_case(case.case_id)
    assert len(events) == 1

    event = events[0]
    assert event.event_type is AuditEventType.REVENUE_RISK_DETECTED
    assert event.meta["payment_id"] == payment.payment_id
    assert event.meta["amount_at_risk"] == 250_000
    assert event.meta["failure_reason"] == FailureReason.INSUFFICIENT_FUNDS.value


def test_reusing_a_case_does_not_duplicate_the_audit_event(detector, audit, payment_factory, db):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    case = detector.detect_and_open_case(payment)
    db.commit()
    detector.detect_and_open_case(payment)
    db.commit()

    assert audit.count_for_case(case.case_id) == 1


def test_get_case_raises_for_an_unknown_id(detector):
    from app.core.errors import RecordNotFound

    with pytest.raises(RecordNotFound):
        detector.get_case("case_does_not_exist")
