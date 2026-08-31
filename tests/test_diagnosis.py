"""Diagnosis engine tests (Requirement 7.1-7.6)."""

from __future__ import annotations

import pytest

from app.core.enums import ActionType, FailureCategory, FailureReason, Transience
from app.services.context_builder import CustomerSnapshot, RecoveryContext
from app.services.diagnosis_engine import (
    Diagnosis,
    DiagnosisEngine,
    RuleBasedDiagnosisEngine,
)


def make_context(
    *,
    failure_reason: FailureReason = FailureReason.BANK_TIMEOUT,
    attempt_count: int = 1,
    failed_actions: frozenset[ActionType] = frozenset(),
) -> RecoveryContext:
    """A context built without touching the database.

    Possible precisely because the context is a frozen value object, which is the
    point of Requirement 6.5.
    """
    from app.core.enums import PaymentMethod, PaymentStatus, SubscriptionStatus

    return RecoveryContext(
        case_id="case_diag",
        payment_id="pay_diag",
        amount=1_000_000,
        currency="INR",
        payment_method=PaymentMethod.UPI,
        payment_status=PaymentStatus.FAILED,
        failure_reason=failure_reason,
        attempt_count=attempt_count,
        merchant_id="merch_test",
        customer=CustomerSnapshot(
            customer_id="cust_diag",
            total_payments=18,
            successful_payments=17,
            failed_payments=1,
            success_rate=0.94,
            average_transaction_value=400_000,
            subscription_status=SubscriptionStatus.ACTIVE,
            history_available=True,
        ),
        transaction_hour=13,
        days_since_previous_payment=30,
        is_returning_customer=True,
        previous_recovery_attempt_count=0,
        attempted_action_types=frozenset(),
        succeeded_action_types=frozenset(),
        failed_action_types=failed_actions,
        unsuccessful_outcome_count=0,
        failure_reason_history=(failure_reason,),
    )


@pytest.fixture
def engine() -> RuleBasedDiagnosisEngine:
    return RuleBasedDiagnosisEngine()


# ---------------------------------------------------------------------------
# Classification table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reason", "category", "transience"),
    [
        (FailureReason.BANK_TIMEOUT, FailureCategory.TRANSIENT, Transience.TRANSIENT),
        (FailureReason.NETWORK_ERROR, FailureCategory.TRANSIENT, Transience.TRANSIENT),
        (FailureReason.EXPIRED_CARD, FailureCategory.CUSTOMER_ACTION, Transience.PERSISTENT),
        (FailureReason.INSUFFICIENT_FUNDS, FailureCategory.TIME_DEPENDENT, Transience.TRANSIENT),
        (FailureReason.CHECKOUT_ABANDONMENT, FailureCategory.ENGAGEMENT, Transience.PERSISTENT),
        (FailureReason.SUBSCRIPTION_FAILURE, FailureCategory.ENGAGEMENT, Transience.TRANSIENT),
        (FailureReason.UNKNOWN, FailureCategory.UNKNOWN, Transience.UNKNOWN),
    ],
)
def test_classification_table(engine, reason, category, transience):
    """Requirement 7.2."""
    diagnosis = engine.diagnose(make_context(failure_reason=reason))
    assert diagnosis.failure_reason is reason
    assert diagnosis.category is category
    assert diagnosis.transience is transience


def test_every_failure_reason_is_classified(engine):
    for reason in FailureReason:
        assert engine.diagnose(make_context(failure_reason=reason)) is not None


def test_bank_timeout_and_network_error_are_transient(engine):
    """Requirement 7.2."""
    for reason in (FailureReason.BANK_TIMEOUT, FailureReason.NETWORK_ERROR):
        assert engine.diagnose(make_context(failure_reason=reason)).is_transient is True


def test_expired_card_is_persistent(engine):
    """Requirement 7.2: retrying the same instrument cannot work."""
    diagnosis = engine.diagnose(make_context(failure_reason=FailureReason.EXPIRED_CARD))
    assert diagnosis.is_transient is False
    assert diagnosis.category is FailureCategory.CUSTOMER_ACTION


# ---------------------------------------------------------------------------
# Unknown handling
# ---------------------------------------------------------------------------


def test_unknown_requires_escalation(engine):
    """Requirement 7.3."""
    diagnosis = engine.diagnose(make_context(failure_reason=FailureReason.UNKNOWN))
    assert diagnosis.requires_escalation is True
    assert "human" in diagnosis.explanation.lower()


def test_known_reasons_do_not_require_escalation_by_default(engine):
    for reason in FailureReason:
        if reason is FailureReason.UNKNOWN:
            continue
        assert engine.diagnose(make_context(failure_reason=reason)).requires_escalation is False


# ---------------------------------------------------------------------------
# Determinism and purity
# ---------------------------------------------------------------------------


def test_repeated_diagnosis_of_unchanged_data_is_identical(engine):
    """Requirement 7.4."""
    context = make_context(failure_reason=FailureReason.INSUFFICIENT_FUNDS)
    assert engine.diagnose(context) == engine.diagnose(context)


def test_diagnosis_is_immutable(engine):
    diagnosis = engine.diagnose(make_context())
    with pytest.raises(Exception):
        diagnosis.category = FailureCategory.UNKNOWN  # type: ignore[misc]


def test_diagnosis_derives_only_from_the_context(engine):
    """Requirement 7.4: no database, no clock, no I/O."""
    # Constructed entirely in memory, so any hidden dependency would fail here.
    assert engine.diagnose(make_context()).failure_reason is FailureReason.BANK_TIMEOUT


# ---------------------------------------------------------------------------
# Explanation quality
# ---------------------------------------------------------------------------


def test_explanation_is_human_readable(engine):
    """Requirement 7.1."""
    explanation = engine.diagnose(
        make_context(failure_reason=FailureReason.BANK_TIMEOUT)
    ).explanation
    assert len(explanation) > 40
    assert "bank" in explanation.lower()


def test_explanation_mentions_repeat_attempts(engine):
    explanation = engine.diagnose(make_context(attempt_count=3)).explanation
    assert "3 times" in explanation


def test_explanation_mentions_previously_failed_actions(engine):
    explanation = engine.diagnose(
        make_context(
            failure_reason=FailureReason.EXPIRED_CARD,
            failed_actions=frozenset({ActionType.RETRY_NOW}),
        )
    ).explanation
    assert "RETRY_NOW" in explanation


# ---------------------------------------------------------------------------
# Substitutability
# ---------------------------------------------------------------------------


def test_rule_based_engine_satisfies_the_protocol(engine):
    """Requirement 7.6: Phase 1 swaps in an LLM diagnoser behind this Protocol."""
    assert isinstance(engine, DiagnosisEngine)


def test_serialization_round_trip(engine):
    """Requirement 7.5: the shape persisted on the case and in audit metadata."""
    payload = engine.diagnose(make_context()).to_dict()
    assert set(payload) == {
        "failure_reason",
        "category",
        "transience",
        "requires_escalation",
        "explanation",
    }
    assert payload["failure_reason"] == "BANK_TIMEOUT"
    assert payload["transience"] == "TRANSIENT"


def test_diagnosis_can_be_constructed_directly():
    diagnosis = Diagnosis(
        failure_reason=FailureReason.BANK_TIMEOUT,
        category=FailureCategory.TRANSIENT,
        transience=Transience.TRANSIENT,
        requires_escalation=False,
        explanation="test",
    )
    assert diagnosis.is_transient is True
