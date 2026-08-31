"""Recovery context tests (Requirement 6.1-6.7)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.enums import (
    ActionStatus,
    ActionType,
    CaseState,
    FailureReason,
    PaymentMethod,
    PaymentStatus,
    RiskLevel,
    SubscriptionStatus,
)
from app.core.errors import RecordNotFound
from app.models import RecoveryAction, RecoveryCase, RecoveryOutcome
from app.services.context_builder import (
    NEUTRAL_SUCCESS_RATE,
    CustomerSnapshot,
    RecoveryContextBuilder,
)


@pytest.fixture
def builder(db, clock) -> RecoveryContextBuilder:
    return RecoveryContextBuilder(session=db, clock=clock)


@pytest.fixture
def case_factory(db, clock):
    counter = {"n": 0}

    def _make(payment, state: CaseState = CaseState.DETECTED, diagnosis=None) -> RecoveryCase:
        counter["n"] += 1
        now = clock.now()
        case = RecoveryCase(
            case_id=f"case_ctx_{counter['n']:04d}",
            payment_id=payment.payment_id,
            state=state,
            amount_at_risk=payment.amount,
            diagnosis=diagnosis,
            created_at=now,
            updated_at=now,
        )
        db.add(case)
        db.commit()
        return case

    return _make


@pytest.fixture
def action_factory(db, clock):
    counter = {"n": 0}

    def _make(
        case,
        action: ActionType,
        *,
        executed: bool = True,
        recovered: bool | None = None,
        scheduled_at=None,
    ) -> RecoveryAction:
        counter["n"] += 1
        now = clock.now()
        record = RecoveryAction(
            action_id=f"act_ctx_{counter['n']:04d}",
            case_id=case.case_id,
            payment_id=case.payment_id,
            action_type=action,
            estimated_probability=0.5,
            confidence=1.0,
            model_version="test",
            expected_recovery_value=1,
            erv_breakdown={},
            risk_level=RiskLevel.LOW,
            decision_explanation={},
            status=ActionStatus.EXECUTED if executed else ActionStatus.SCHEDULED,
            created_at=now,
            scheduled_at=scheduled_at,
            executed_at=now if executed else None,
        )
        db.add(record)
        db.commit()

        if recovered is not None:
            db.add(
                RecoveryOutcome(
                    outcome_id=f"out_ctx_{counter['n']:04d}",
                    action_id=record.action_id,
                    previous_payment_status=PaymentStatus.FAILED,
                    new_payment_status=(
                        PaymentStatus.SUCCEEDED if recovered else PaymentStatus.FAILED
                    ),
                    recovered=recovered,
                    recovered_amount=1_000_000 if recovered else 0,
                    verification_timestamp=now,
                )
            )
            db.commit()
        return record

    return _make


# ---------------------------------------------------------------------------
# Field population
# ---------------------------------------------------------------------------


def test_context_carries_payment_and_customer_facts(
    builder, case_factory, payment_factory, customer_factory
):
    """Requirement 6.1, 6.2."""
    customer = customer_factory(success_rate=0.94, total_payments=18, failed_payments=1)
    payment = payment_factory(
        customer=customer,
        amount=1_000_000,
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.BANK_TIMEOUT,
        payment_method=PaymentMethod.UPI,
        attempt_count=1,
    )
    context = builder.build(case_factory(payment))

    assert context.payment_id == payment.payment_id
    assert context.amount == 1_000_000
    assert context.currency == "INR"
    assert context.payment_method is PaymentMethod.UPI
    assert context.failure_reason is FailureReason.BANK_TIMEOUT
    assert context.attempt_count == 1
    assert context.customer.success_rate == pytest.approx(0.94)
    assert context.customer.total_payments == 18
    assert context.customer.failed_payments == 1
    assert context.customer.history_available is True
    assert context.is_returning_customer is True


def test_features_expose_every_required_key(builder, case_factory, payment_factory):
    """Requirement 6.2."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    features = builder.build(case_factory(payment)).features()

    required = {
        "payment_amount",
        "payment_method",
        "failure_reason",
        "attempt_count",
        "customer_success_rate",
        "customer_failed_payments",
        "customer_total_payments",
        "subscription",
        "transaction_hour",
        "is_returning_customer",
        "days_since_previous_payment",
        "previous_recovery_attempt_count",
        "attempted_action_types",
    }
    assert required.issubset(features)


def test_transaction_hour_comes_from_the_stored_timestamp(
    builder, case_factory, payment_factory, clock
):
    """Requirement 6.3: 13:00 simulation start means hour 13."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    assert builder.build(case_factory(payment)).transaction_hour == 13

    # Advancing the clock does not retroactively change the payment's hour.
    clock.advance(hours=5)
    assert builder.build(case_factory(payment)).transaction_hour == 13


def test_subscription_status_is_exposed(builder, case_factory, payment_factory, customer_factory):
    subscriber = customer_factory(subscription=SubscriptionStatus.ACTIVE)
    payment = payment_factory(customer=subscriber, status=PaymentStatus.FAILED,
                              failure_reason=FailureReason.BANK_TIMEOUT)
    context = builder.build(case_factory(payment))

    assert context.customer.subscription_status is SubscriptionStatus.ACTIVE
    assert context.customer.is_subscriber is True
    assert context.features()["subscription"] is True


def test_missing_failure_reason_resolves_to_unknown(builder, case_factory, payment_factory):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=None)
    assert builder.build(case_factory(payment)).failure_reason is FailureReason.UNKNOWN


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_repeated_builds_produce_identical_features(builder, case_factory, payment_factory):
    """Requirement 6.4, 25.5: the reproducibility foundation."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    case = case_factory(payment)

    assert builder.build(case).features() == builder.build(case).features()


def test_repeated_builds_are_equal_objects(builder, case_factory, payment_factory):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    case = case_factory(payment)
    assert builder.build(case) == builder.build(case)


def test_context_is_immutable(builder, case_factory, payment_factory):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    context = builder.build(case_factory(payment))
    with pytest.raises(Exception):
        context.amount = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Missing customer
# ---------------------------------------------------------------------------


def test_missing_customer_yields_neutral_defaults(builder, case_factory, payment_factory, db):
    """Requirement 6.7."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    case = case_factory(payment)

    # Detach the customer without deleting the payment.
    payment.customer_id = "cust_vanished"
    db.commit()

    context = builder.build(case)
    assert context.customer.history_available is False
    assert context.customer.success_rate == NEUTRAL_SUCCESS_RATE
    assert context.customer.total_payments == 0
    assert context.is_returning_customer is False


def test_customer_snapshot_unavailable_helper():
    snapshot = CustomerSnapshot.unavailable("cust_x")
    assert snapshot.history_available is False
    assert snapshot.success_rate == NEUTRAL_SUCCESS_RATE
    assert snapshot.is_subscriber is False


def test_missing_payment_raises(builder, case_factory, payment_factory, db):
    payment = payment_factory(status=PaymentStatus.FAILED)
    case = case_factory(payment)
    case.payment_id = "pay_vanished"
    db.commit()

    with pytest.raises(RecordNotFound):
        builder.build(case)


# ---------------------------------------------------------------------------
# Recovery history
# ---------------------------------------------------------------------------


def test_attempted_and_failed_action_types_are_tracked(
    builder, case_factory, payment_factory, action_factory
):
    """Requirement 6.2: what has already been tried, and what did not work."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.EXPIRED_CARD)
    case = case_factory(payment)

    action_factory(case, ActionType.RETRY_NOW, executed=True, recovered=False)

    context = builder.build(case)
    assert ActionType.RETRY_NOW in context.attempted_action_types
    assert ActionType.RETRY_NOW in context.failed_action_types
    assert context.has_previously_failed(ActionType.RETRY_NOW) is True
    assert context.previous_recovery_attempt_count == 1
    assert context.unsuccessful_outcome_count == 1


def test_succeeded_action_types_are_tracked(
    builder, case_factory, payment_factory, action_factory
):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    case = case_factory(payment)

    action_factory(case, ActionType.SEND_PAYMENT_LINK, executed=True, recovered=True)

    context = builder.build(case)
    assert context.has_previously_succeeded(ActionType.SEND_PAYMENT_LINK) is True
    assert context.unsuccessful_outcome_count == 0


def test_customer_level_success_history_crosses_payments(
    builder, case_factory, payment_factory, action_factory, customer_factory
):
    """A channel that worked before for this customer is evidence it may work again."""
    customer = customer_factory()
    earlier = payment_factory(customer=customer, status=PaymentStatus.SUCCEEDED)
    earlier_case = case_factory(earlier)
    action_factory(earlier_case, ActionType.SEND_PAYMENT_LINK, executed=True, recovered=True)

    current = payment_factory(
        customer=customer, status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT
    )
    context = builder.build(case_factory(current))

    assert context.has_previously_succeeded(ActionType.SEND_PAYMENT_LINK) is True


def test_unexecuted_action_is_not_counted_as_attempted(
    builder, case_factory, payment_factory, action_factory, clock
):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    case = case_factory(payment)

    scheduled = clock.now() + timedelta(minutes=15)
    action_factory(case, ActionType.RETRY_LATER, executed=False, scheduled_at=scheduled)

    context = builder.build(case)
    assert context.attempted_action_types == frozenset()
    assert context.previous_recovery_attempt_count == 0
    assert context.scheduled_at == scheduled
    assert context.pending_action_id is not None


def test_failure_reason_history_is_collected(builder, case_factory, payment_factory, db, clock):
    from app.models import PaymentAttempt

    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    for index, reason in enumerate(
        [FailureReason.BANK_TIMEOUT, FailureReason.BANK_TIMEOUT], start=1
    ):
        db.add(
            PaymentAttempt(
                attempt_id=f"att_hist_{index}",
                payment_id=payment.payment_id,
                attempt_number=index,
                status=PaymentStatus.FAILED,
                failure_reason=reason,
                provider_response={},
                source="checkout",
                attempted_at=clock.now(),
            )
        )
    db.commit()

    context = builder.build(case_factory(payment))
    assert context.failure_reason_history == (
        FailureReason.BANK_TIMEOUT,
        FailureReason.BANK_TIMEOUT,
    )


def test_days_since_previous_payment(builder, case_factory, payment_factory, customer_factory, db, clock):
    customer = customer_factory()
    first = payment_factory(customer=customer, status=PaymentStatus.SUCCEEDED)

    clock.advance(hours=24 * 30)
    later = payment_factory(
        customer=customer, status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT
    )
    later.created_at = clock.now()
    db.commit()

    context = builder.build(case_factory(later))
    assert context.days_since_previous_payment == 30
    assert first.created_at < later.created_at


def test_days_since_previous_payment_is_none_for_a_first_payment(
    builder, case_factory, payment_factory
):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    assert builder.build(case_factory(payment)).days_since_previous_payment is None


def test_diagnosis_is_carried_as_a_mapping(builder, case_factory, payment_factory):
    """Kept untyped so this module has no edge to the diagnosis engine."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    case = case_factory(payment, diagnosis={"failure_reason": "BANK_TIMEOUT"})
    assert builder.build(case).diagnosis == {"failure_reason": "BANK_TIMEOUT"}
