"""Candidate generation tests (Requirement 8.1-8.10, 25.6)."""

from __future__ import annotations

import pytest

from app.core.enums import ActionType, FailureReason
from app.services.candidate_generator import (
    CANDIDATES_BY_REASON,
    RecoveryActionCandidateGenerator,
)
from app.services.diagnosis_engine import RuleBasedDiagnosisEngine
from tests.test_diagnosis import make_context


@pytest.fixture
def generator() -> RecoveryActionCandidateGenerator:
    return RecoveryActionCandidateGenerator()


@pytest.fixture
def diagnose():
    engine = RuleBasedDiagnosisEngine()
    return engine.diagnose


def candidates_for(generator, diagnose, reason, **kwargs):
    context = make_context(failure_reason=reason, **kwargs)
    return generator.generate(context, diagnose(context))


# ---------------------------------------------------------------------------
# Per-reason candidate sets (Requirement 25.6)
# ---------------------------------------------------------------------------


def test_bank_timeout_candidates(generator, diagnose):
    """Requirement 8.2."""
    assert candidates_for(generator, diagnose, FailureReason.BANK_TIMEOUT) == [
        ActionType.RETRY_NOW,
        ActionType.RETRY_LATER,
        ActionType.SEND_PAYMENT_LINK,
    ]


def test_expired_card_candidates(generator, diagnose):
    """Requirement 8.3: no plain retry, because the instrument cannot work."""
    result = candidates_for(generator, diagnose, FailureReason.EXPIRED_CARD)
    assert result == [
        ActionType.CHANGE_PAYMENT_METHOD,
        ActionType.SEND_PAYMENT_LINK,
        ActionType.ESCALATE_HUMAN,
    ]
    assert ActionType.RETRY_NOW not in result


def test_insufficient_funds_candidates(generator, diagnose):
    """Requirement 8.4."""
    assert candidates_for(generator, diagnose, FailureReason.INSUFFICIENT_FUNDS) == [
        ActionType.RETRY_LATER,
        ActionType.SEND_PAYMENT_LINK,
        ActionType.SEND_REMINDER,
    ]


def test_checkout_abandonment_candidates(generator, diagnose):
    """Requirement 8.5: engagement, not retrying."""
    result = candidates_for(generator, diagnose, FailureReason.CHECKOUT_ABANDONMENT)
    assert result == [ActionType.SEND_REMINDER, ActionType.SEND_PAYMENT_LINK]
    assert ActionType.RETRY_NOW not in result


def test_network_error_candidates(generator, diagnose):
    """Requirement 8.6."""
    assert candidates_for(generator, diagnose, FailureReason.NETWORK_ERROR) == [
        ActionType.RETRY_NOW,
        ActionType.RETRY_LATER,
    ]


def test_subscription_failure_candidates(generator, diagnose):
    """Requirement 8.7."""
    assert candidates_for(generator, diagnose, FailureReason.SUBSCRIPTION_FAILURE) == [
        ActionType.RETRY_LATER,
        ActionType.SEND_REMINDER,
        ActionType.SEND_PAYMENT_LINK,
    ]


def test_unknown_candidates(generator, diagnose):
    """Requirement 8.8: no automated financial action for an unknown cause."""
    result = candidates_for(generator, diagnose, FailureReason.UNKNOWN)
    assert result == [ActionType.ESCALATE_HUMAN, ActionType.STOP]
    assert not (set(result) & ActionType.retry_actions())


def test_every_failure_reason_has_candidates():
    """No reason falls through to an empty list."""
    for reason in FailureReason:
        assert CANDIDATES_BY_REASON[reason], f"{reason.value} has no candidates"


# ---------------------------------------------------------------------------
# Generation contract
# ---------------------------------------------------------------------------


def test_generator_returns_candidates_not_a_selection(generator, diagnose):
    """Requirement 8.1."""
    result = candidates_for(generator, diagnose, FailureReason.BANK_TIMEOUT)
    assert isinstance(result, list)
    assert len(result) > 1


def test_generation_is_deterministic(generator, diagnose):
    first = candidates_for(generator, diagnose, FailureReason.BANK_TIMEOUT)
    second = candidates_for(generator, diagnose, FailureReason.BANK_TIMEOUT)
    assert first == second


def test_returned_list_is_a_copy(generator, diagnose):
    """Mutating the result must not corrupt the table."""
    result = candidates_for(generator, diagnose, FailureReason.BANK_TIMEOUT)
    result.append(ActionType.STOP)
    assert ActionType.STOP not in CANDIDATES_BY_REASON[FailureReason.BANK_TIMEOUT]


# ---------------------------------------------------------------------------
# Filtering previously failed actions (Requirement 8.10)
# ---------------------------------------------------------------------------


def test_previously_failed_action_is_dropped(generator, diagnose):
    """The expired-card path moves on after RETRY_NOW fails."""
    result = candidates_for(
        generator,
        diagnose,
        FailureReason.EXPIRED_CARD,
        failed_actions=frozenset({ActionType.CHANGE_PAYMENT_METHOD}),
    )
    assert ActionType.CHANGE_PAYMENT_METHOD not in result
    assert ActionType.SEND_PAYMENT_LINK in result


def test_filtering_never_empties_the_candidate_list(generator, diagnose):
    """Requirement 8.10: an exhausted case still needs a disposition."""
    result = candidates_for(
        generator,
        diagnose,
        FailureReason.NETWORK_ERROR,
        failed_actions=frozenset({ActionType.RETRY_NOW, ActionType.RETRY_LATER}),
    )
    assert result == [ActionType.RETRY_NOW, ActionType.RETRY_LATER]


def test_escalate_and_stop_are_never_filtered(generator, diagnose):
    """Terminal dispositions stay available regardless of history."""
    result = candidates_for(
        generator,
        diagnose,
        FailureReason.UNKNOWN,
        failed_actions=frozenset({ActionType.ESCALATE_HUMAN, ActionType.STOP}),
    )
    assert result == [ActionType.ESCALATE_HUMAN, ActionType.STOP]


def test_unrelated_failed_action_does_not_affect_candidates(generator, diagnose):
    result = candidates_for(
        generator,
        diagnose,
        FailureReason.BANK_TIMEOUT,
        failed_actions=frozenset({ActionType.SEND_REMINDER}),
    )
    assert result == [
        ActionType.RETRY_NOW,
        ActionType.RETRY_LATER,
        ActionType.SEND_PAYMENT_LINK,
    ]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def test_candidates_for_helper_reports_the_table(generator):
    assert generator.candidates_for(FailureReason.BANK_TIMEOUT) == (
        ActionType.RETRY_NOW,
        ActionType.RETRY_LATER,
        ActionType.SEND_PAYMENT_LINK,
    )
