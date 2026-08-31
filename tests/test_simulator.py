"""Payment simulator tests (Requirement 14.1-14.12, 25.11)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from app.core.enums import (
    ActionType,
    AuditEventType,
    ExecutionStatus,
    FailureReason,
    PaymentStatus,
)
from app.integrations.action_executor import ActionExecutor, ExecutionResult
from app.integrations.payment_simulator import (
    SCRIPTED_OUTCOMES,
    PaymentSimulatorExecutor,
    ScriptedOutcome,
    outcome_draw,
)
from app.services.audit_service import AuditService
from app.services.context_builder import RecoveryContextBuilder
from tests.test_predictor import context_with


@pytest.fixture
def simulator(db, settings, clock) -> PaymentSimulatorExecutor:
    return PaymentSimulatorExecutor(session=db, settings=settings, clock=clock)


@pytest.fixture
def case_for(db, clock):
    """Persist a failed payment plus its case, and return a real context."""
    from app.core.enums import CaseState
    from app.models import RecoveryCase

    counter = {"n": 0}

    def _make(payment):
        counter["n"] += 1
        now = clock.now()
        case = RecoveryCase(
            case_id=f"case_sim_{counter['n']:04d}",
            payment_id=payment.payment_id,
            state=CaseState.DETECTED,
            amount_at_risk=payment.amount,
            created_at=now,
            updated_at=now,
        )
        db.add(case)
        db.commit()
        return RecoveryContextBuilder(session=db, clock=clock).build(case)

    return _make


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_simulator_satisfies_the_executor_protocol(simulator):
    """Requirement 14.11: the seam a provider executor plugs into."""
    assert isinstance(simulator, ActionExecutor)


def test_simulator_supports_every_action(simulator):
    """Requirement 14.3."""
    assert simulator.supported_actions == frozenset(ActionType)
    for action in ActionType:
        assert simulator.supports(action) is True


def test_execution_result_carries_every_required_field(simulator, payment_factory, case_for):
    """Requirement 14.1."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    result = simulator.execute(ActionType.RETRY_LATER, case_for(payment))

    assert isinstance(result, ExecutionResult)
    assert result.action is ActionType.RETRY_LATER
    assert result.status in set(ExecutionStatus)
    assert result.provider_response["simulated"] is True
    assert result.executed_at is not None


def test_executed_at_comes_from_the_virtual_clock(simulator, payment_factory, case_for, clock):
    clock.advance(minutes=42)
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    result = simulator.execute(ActionType.RETRY_LATER, case_for(payment))
    assert result.executed_at == clock.now()


def test_no_external_provider_is_contacted(simulator, payment_factory, case_for):
    """Requirement 14.2: every response is locally synthesised."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    result = simulator.execute(ActionType.RETRY_LATER, case_for(payment))
    assert result.provider_response["provider"] == "payment_simulator"


# ---------------------------------------------------------------------------
# Scripted behaviours (Requirement 14.5-14.7)
# ---------------------------------------------------------------------------


def test_bank_timeout_recovers_on_retry_later(simulator, payment_factory, case_for, db):
    """Requirement 14.5: always succeeds."""
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT, attempt_count=1
    )
    result = simulator.execute(ActionType.RETRY_LATER, case_for(payment))
    db.commit()

    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.provider_response["decision_basis"] == "scripted"
    db.refresh(payment)
    assert payment.status is PaymentStatus.SUCCEEDED


def test_expired_card_refuses_retry_now(simulator, payment_factory, case_for, db):
    """Requirement 14.6: always fails."""
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.EXPIRED_CARD, attempt_count=1
    )
    result = simulator.execute(ActionType.RETRY_NOW, case_for(payment))
    db.commit()

    assert result.status is ExecutionStatus.FAILED
    db.refresh(payment)
    assert payment.status is PaymentStatus.FAILED
    assert payment.failure_reason is FailureReason.EXPIRED_CARD


def test_expired_card_recovers_on_change_payment_method(simulator, payment_factory, case_for, db):
    """Requirement 14.6: always succeeds."""
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.EXPIRED_CARD, attempt_count=1
    )
    result = simulator.execute(ActionType.CHANGE_PAYMENT_METHOD, case_for(payment))
    db.commit()

    assert result.status is ExecutionStatus.SUCCEEDED
    db.refresh(payment)
    assert payment.status is PaymentStatus.SUCCEEDED
    assert payment.failure_reason is None


@pytest.mark.parametrize("action", [ActionType.RETRY_NOW, ActionType.RETRY_LATER])
def test_insufficient_funds_refuses_retries(simulator, payment_factory, case_for, db, action):
    """Requirement 14.7: retries keep failing so the budget is exhausted."""
    payment = payment_factory(
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS,
        attempt_count=1,
    )
    result = simulator.execute(action, case_for(payment))
    db.commit()

    assert result.status is ExecutionStatus.FAILED
    db.refresh(payment)
    assert payment.status is PaymentStatus.FAILED


def test_insufficient_funds_retries_fail_repeatedly(simulator, payment_factory, case_for, db):
    """Requirement 14.7: repeated, not merely one."""
    payment = payment_factory(
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS,
        attempt_count=1,
    )
    for _ in range(4):
        context = case_for(payment)
        assert simulator.execute(ActionType.RETRY_LATER, context).status is ExecutionStatus.FAILED
        db.commit()

    db.refresh(payment)
    assert payment.status is PaymentStatus.FAILED
    assert payment.attempt_count == 5


def test_scripted_table_covers_the_required_pairs():
    """Requirement 14.5-14.7."""
    assert (
        SCRIPTED_OUTCOMES[(FailureReason.BANK_TIMEOUT, ActionType.RETRY_LATER)]
        is ScriptedOutcome.ALWAYS_SUCCEED
    )
    assert (
        SCRIPTED_OUTCOMES[(FailureReason.EXPIRED_CARD, ActionType.RETRY_NOW)]
        is ScriptedOutcome.ALWAYS_FAIL
    )
    assert (
        SCRIPTED_OUTCOMES[(FailureReason.EXPIRED_CARD, ActionType.CHANGE_PAYMENT_METHOD)]
        is ScriptedOutcome.ALWAYS_SUCCEED
    )
    assert (
        SCRIPTED_OUTCOMES[(FailureReason.INSUFFICIENT_FUNDS, ActionType.RETRY_LATER)]
        is ScriptedOutcome.ALWAYS_FAIL
    )


# ---------------------------------------------------------------------------
# Non-charge behaviours (Requirement 14.3)
# ---------------------------------------------------------------------------


def test_escalation_touches_no_payment(simulator, payment_factory, case_for, db):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.UNKNOWN)
    before = payment.attempt_count

    result = simulator.execute(ActionType.ESCALATE_HUMAN, case_for(payment))
    db.commit()

    assert result.status is ExecutionStatus.ESCALATED
    assert result.provider_response["payment_touched"] is False
    assert result.attempted_charge is False
    db.refresh(payment)
    assert payment.status is PaymentStatus.FAILED
    assert payment.attempt_count == before


def test_stopped_action_touches_no_payment(simulator, payment_factory, case_for, db):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.UNKNOWN)
    result = simulator.execute(ActionType.STOP, case_for(payment))
    db.commit()

    assert result.status is ExecutionStatus.STOPPED
    assert result.provider_response["payment_touched"] is False


def test_payment_link_is_a_customer_channel(simulator, payment_factory, case_for):
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.CHECKOUT_ABANDONMENT
    )
    result = simulator.execute(ActionType.SEND_PAYMENT_LINK, case_for(payment))
    assert result.provider_response["channel"] == "customer_channel"


def test_retry_is_a_direct_charge(simulator, payment_factory, case_for):
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    result = simulator.execute(ActionType.RETRY_NOW, case_for(payment))
    assert result.provider_response["channel"] == "direct_charge"


def test_alternative_payment_recovery_is_simulated(simulator, payment_factory, case_for, db):
    """Requirement 14.3: alternative payment method recovery."""
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.EXPIRED_CARD, attempt_count=1
    )
    result = simulator.execute(ActionType.CHANGE_PAYMENT_METHOD, case_for(payment))
    db.commit()

    assert result.status is ExecutionStatus.SUCCEEDED
    db.refresh(payment)
    assert payment.attempts[-1].action_type is ActionType.CHANGE_PAYMENT_METHOD


# ---------------------------------------------------------------------------
# Delayed retry (Requirement 14.3)
# ---------------------------------------------------------------------------


def test_schedule_defers_without_touching_the_payment(simulator, payment_factory, case_for, db, clock):
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT, attempt_count=1
    )
    before = payment.attempt_count
    due = clock.now() + timedelta(minutes=15)

    result = simulator.schedule(ActionType.RETRY_LATER, case_for(payment), due)
    db.commit()

    assert result.status is ExecutionStatus.SCHEDULED
    assert result.attempted_charge is False
    assert result.provider_response["scheduled_at"] == due.isoformat()
    db.refresh(payment)
    assert payment.attempt_count == before
    assert payment.status is PaymentStatus.FAILED


# ---------------------------------------------------------------------------
# Determinism (Requirement 14.8, 25.11)
# ---------------------------------------------------------------------------


def test_outcome_draw_is_reproducible():
    """Requirement 25.11."""
    first = outcome_draw(20260101, "pay_0001", ActionType.SEND_PAYMENT_LINK, 2)
    second = outcome_draw(20260101, "pay_0001", ActionType.SEND_PAYMENT_LINK, 2)
    assert first == second
    assert 0.0 <= first < 1.0


def test_outcome_draw_varies_with_every_input():
    base = outcome_draw(20260101, "pay_0001", ActionType.SEND_PAYMENT_LINK, 1)
    assert base != outcome_draw(20260102, "pay_0001", ActionType.SEND_PAYMENT_LINK, 1)
    assert base != outcome_draw(20260101, "pay_0002", ActionType.SEND_PAYMENT_LINK, 1)
    assert base != outcome_draw(20260101, "pay_0001", ActionType.SEND_REMINDER, 1)
    assert base != outcome_draw(20260101, "pay_0001", ActionType.SEND_PAYMENT_LINK, 2)


def test_draw_is_independent_of_execution_order():
    """Why a hash and not a shared RNG stream."""
    forward = [
        outcome_draw(1, f"pay_{index}", ActionType.SEND_REMINDER, 1) for index in range(5)
    ]
    backward = [
        outcome_draw(1, f"pay_{index}", ActionType.SEND_REMINDER, 1)
        for index in reversed(range(5))
    ]
    assert forward == list(reversed(backward))


def test_identical_inputs_produce_identical_outcomes(db, settings, clock, payment_factory, case_for):
    """Requirement 14.8: same seed, same payment, same attempt, same result."""
    payment = payment_factory(
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.CHECKOUT_ABANDONMENT,
        payment_id="pay_determinism",
        attempt_count=1,
    )
    context = case_for(payment)

    first = PaymentSimulatorExecutor(session=db, settings=settings, clock=clock)._decide_outcome(
        FailureReason.CHECKOUT_ABANDONMENT, ActionType.SEND_REMINDER, payment.payment_id, 2
    )
    second = PaymentSimulatorExecutor(session=db, settings=settings, clock=clock)._decide_outcome(
        FailureReason.CHECKOUT_ABANDONMENT, ActionType.SEND_REMINDER, payment.payment_id, 2
    )
    assert first == second


def test_seed_change_can_change_the_outcome(db, clock, payment_factory, case_for):
    from app.core.config import Settings

    payment = payment_factory(
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.CHECKOUT_ABANDONMENT,
        payment_id="pay_seedchange",
        attempt_count=1,
    )
    draws = {
        seed: outcome_draw(seed, payment.payment_id, ActionType.SEND_REMINDER, 2)
        for seed in (1, 2, 3, 4, 5)
    }
    assert len(set(draws.values())) == 5


def test_unscripted_pair_reports_its_reasoning(simulator, payment_factory, case_for):
    """Transparency: a demo can show whether an outcome was scripted or drawn."""
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.CHECKOUT_ABANDONMENT
    )
    result = simulator.execute(ActionType.SEND_REMINDER, case_for(payment))

    response = result.provider_response
    assert response["decision_basis"] == "seeded_draw"
    assert "draw" in response
    assert "success_threshold" in response
    assert response["seed"] == 20260101


def test_scenario_probabilities_come_from_configuration(db, clock, payment_factory, case_for):
    """Requirement 14.9."""
    from app.core.config import Settings

    always = Settings(
        _env_file=None,
        simulator_success_probability={"CHECKOUT_ABANDONMENT:SEND_REMINDER": 1.0},
    )
    never = Settings(
        _env_file=None,
        simulator_success_probability={"CHECKOUT_ABANDONMENT:SEND_REMINDER": 0.0},
    )

    payment_a = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.CHECKOUT_ABANDONMENT
    )
    payment_b = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.CHECKOUT_ABANDONMENT
    )

    succeeded = PaymentSimulatorExecutor(session=db, settings=always, clock=clock).execute(
        ActionType.SEND_REMINDER, case_for(payment_a)
    )
    failed = PaymentSimulatorExecutor(session=db, settings=never, clock=clock).execute(
        ActionType.SEND_REMINDER, case_for(payment_b)
    )
    db.commit()

    assert succeeded.status is ExecutionStatus.SUCCEEDED
    assert failed.status is ExecutionStatus.FAILED


# ---------------------------------------------------------------------------
# Payment state and attempts (Requirement 14.10)
# ---------------------------------------------------------------------------


def test_success_updates_status_and_records_an_attempt(simulator, payment_factory, case_for, db):
    """Requirement 14.10."""
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT, attempt_count=1
    )
    simulator.execute(ActionType.RETRY_LATER, case_for(payment))
    db.commit()
    db.refresh(payment)

    assert payment.status is PaymentStatus.SUCCEEDED
    assert payment.attempt_count == 2
    latest = payment.attempts[-1]
    assert latest.status is PaymentStatus.SUCCEEDED
    assert latest.action_type is ActionType.RETRY_LATER
    assert latest.source == "recovery_action"


def test_failure_records_an_attempt_and_preserves_the_reason(
    simulator, payment_factory, case_for, db
):
    payment = payment_factory(
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS,
        attempt_count=1,
    )
    simulator.execute(ActionType.RETRY_LATER, case_for(payment))
    db.commit()
    db.refresh(payment)

    assert payment.status is PaymentStatus.FAILED
    assert payment.failure_reason is FailureReason.INSUFFICIENT_FUNDS
    assert payment.attempt_count == 2
    assert payment.attempts[-1].failure_reason is FailureReason.INSUFFICIENT_FUNDS


def test_missing_payment_raises(simulator, payment_factory, case_for, db):
    from app.core.errors import RecordNotFound

    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    context = replace(case_for(payment), payment_id="pay_vanished")

    with pytest.raises(RecordNotFound):
        simulator.execute(ActionType.RETRY_NOW, context)


# ---------------------------------------------------------------------------
# Audit (Requirement 14.12)
# ---------------------------------------------------------------------------


def test_successful_execution_records_action_executed(simulator, payment_factory, case_for, db, clock):
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT, attempt_count=1
    )
    context = case_for(payment)
    audit = AuditService(session=db, clock=clock)

    simulator.execute(ActionType.RETRY_LATER, context, audit=audit, workflow_id="wf_sim")
    db.commit()

    events = audit.for_case(context.case_id)
    assert [event.event_type for event in events] == [AuditEventType.ACTION_EXECUTED]
    metadata = events[0].meta
    assert metadata["action"] == "RETRY_LATER"
    assert metadata["execution_status"] == "SUCCEEDED"
    assert metadata["provider_response"]["simulated"] is True
    assert metadata["workflow_id"] == "wf_sim"


def test_failed_execution_records_action_failed(simulator, payment_factory, case_for, db, clock):
    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.EXPIRED_CARD, attempt_count=1
    )
    context = case_for(payment)
    audit = AuditService(session=db, clock=clock)

    simulator.execute(ActionType.RETRY_NOW, context, audit=audit, workflow_id="wf_sim")
    db.commit()

    assert audit.event_types_for_case(context.case_id) == [AuditEventType.ACTION_FAILED]


def test_execution_without_audit_still_works(simulator, payment_factory, case_for):
    """The simulator is usable in isolation."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    assert simulator.execute(ActionType.RETRY_LATER, case_for(payment)) is not None


def test_reported_success_is_not_proof_of_recovery(simulator, payment_factory, case_for):
    """Requirement 15.2 precondition: the executor only reports a claim."""
    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    result = simulator.execute(ActionType.RETRY_LATER, case_for(payment))

    assert result.reported_success is True
    # Verification is a separate component's job; nothing here asserts recovery.
    assert "recovered" not in result.provider_response
