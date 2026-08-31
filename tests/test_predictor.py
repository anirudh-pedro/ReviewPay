"""Deterministic recovery predictor tests (Requirement 9.1-9.9)."""

from __future__ import annotations

import pytest

from app.core.enums import ActionType, FailureReason, SubscriptionStatus
from app.ml.deterministic_scorer import DeterministicRecoveryScorer
from app.ml.predictor import PredictionResult, RecoveryPredictor, ScoringFactor
from app.ml.scoring_tables import (
    BASE_RATE,
    MAX_PROBABILITY,
    MIN_PROBABILITY,
    base_rate,
)
from app.services.context_builder import CustomerSnapshot, RecoveryContext
from tests.test_diagnosis import make_context


@pytest.fixture
def scorer() -> DeterministicRecoveryScorer:
    return DeterministicRecoveryScorer()


def context_with(
    *,
    reason: FailureReason = FailureReason.BANK_TIMEOUT,
    attempt_count: int = 1,
    success_rate: float = 0.94,
    subscriber: bool = True,
    succeeded: frozenset[ActionType] = frozenset(),
    failed: frozenset[ActionType] = frozenset(),
    history_available: bool = True,
) -> RecoveryContext:
    base = make_context(failure_reason=reason, attempt_count=attempt_count)
    snapshot = CustomerSnapshot(
        customer_id="cust_pred",
        total_payments=18,
        successful_payments=17,
        failed_payments=1,
        success_rate=success_rate,
        average_transaction_value=400_000,
        subscription_status=(
            SubscriptionStatus.ACTIVE if subscriber else SubscriptionStatus.NONE
        ),
        history_available=history_available,
    )
    return RecoveryContext(
        **{
            **base.__dict__,
            "customer": snapshot,
            "succeeded_action_types": succeeded,
            "failed_action_types": failed,
        }
    )


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_scorer_satisfies_the_predictor_protocol(scorer):
    """Requirement 9.9: Phase 1 swaps a model in behind this Protocol."""
    assert isinstance(scorer, RecoveryPredictor)


def test_result_carries_every_required_field(scorer):
    """Requirement 9.1."""
    result = scorer.predict(context_with(), ActionType.RETRY_LATER)

    assert isinstance(result.probability, float)
    assert isinstance(result.confidence, float)
    assert result.model_version == "deterministic-scorer-v1"
    assert result.features_used
    assert result.explanation
    assert all(isinstance(factor, ScoringFactor) for factor in result.explanation)


def test_model_version_names_the_deterministic_scorer(scorer):
    """Requirement 9.5."""
    assert "deterministic" in scorer.predict(context_with(), ActionType.RETRY_NOW).model_version


def test_features_used_are_reported(scorer):
    """Requirement 9.6."""
    result = scorer.predict(context_with(), ActionType.RETRY_LATER)
    assert "failure_reason" in result.features_used
    assert "attempt_count" in result.features_used
    assert "customer_success_rate" in result.features_used


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", list(FailureReason))
@pytest.mark.parametrize("action", list(ActionType))
def test_probability_is_always_within_bounds(scorer, reason, action):
    """Requirement 9.2: holds for every reason/action pair."""
    result = scorer.predict(context_with(reason=reason), action)
    assert 0.0 <= result.probability <= 1.0
    assert MIN_PROBABILITY <= result.probability <= MAX_PROBABILITY


def test_extreme_attempt_count_stays_above_the_floor(scorer):
    result = scorer.predict(context_with(attempt_count=50), ActionType.RETRY_NOW)
    assert result.probability >= MIN_PROBABILITY


def test_perfect_customer_stays_below_the_ceiling(scorer):
    result = scorer.predict(
        context_with(attempt_count=0, success_rate=1.0, succeeded=frozenset({ActionType.RETRY_LATER})),
        ActionType.RETRY_LATER,
    )
    assert result.probability <= MAX_PROBABILITY


def test_confidence_is_within_bounds(scorer):
    for reason in FailureReason:
        result = scorer.predict(context_with(reason=reason), ActionType.RETRY_LATER)
        assert 0.0 <= result.confidence <= 1.0


def test_prediction_result_rejects_an_out_of_range_probability():
    with pytest.raises(ValueError, match="probability"):
        PredictionResult(
            probability=1.5,
            confidence=0.5,
            model_version="test",
            features_used=(),
            explanation=(),
        )


# ---------------------------------------------------------------------------
# Purity and determinism
# ---------------------------------------------------------------------------


def test_repeated_prediction_is_identical(scorer):
    """Requirement 9.4."""
    context = context_with()
    first = scorer.predict(context, ActionType.RETRY_LATER)
    second = scorer.predict(context, ActionType.RETRY_LATER)

    assert first.probability == second.probability
    assert first.confidence == second.confidence
    assert first == second


def test_two_scorer_instances_agree(scorer):
    context = context_with()
    other = DeterministicRecoveryScorer()
    assert scorer.predict(context, ActionType.RETRY_NOW) == other.predict(
        context, ActionType.RETRY_NOW
    )


# ---------------------------------------------------------------------------
# Required orderings (Requirement 9.7)
# ---------------------------------------------------------------------------


def test_retry_later_outranks_retry_now_for_bank_timeout(scorer):
    """Requirement 9.7: waiting is the lever for a transient bank fault."""
    context = context_with(reason=FailureReason.BANK_TIMEOUT)
    later = scorer.predict(context, ActionType.RETRY_LATER).probability
    now = scorer.predict(context, ActionType.RETRY_NOW).probability
    assert later > now


def test_change_payment_method_outranks_retry_now_for_expired_card(scorer):
    """Requirement 9.7: retrying a dead instrument cannot work."""
    context = context_with(reason=FailureReason.EXPIRED_CARD)
    change = scorer.predict(context, ActionType.CHANGE_PAYMENT_METHOD).probability
    now = scorer.predict(context, ActionType.RETRY_NOW).probability
    assert change > now
    assert change > 3 * now


def test_retry_later_outranks_retry_now_for_insufficient_funds(scorer):
    context = context_with(reason=FailureReason.INSUFFICIENT_FUNDS)
    assert (
        scorer.predict(context, ActionType.RETRY_LATER).probability
        > scorer.predict(context, ActionType.RETRY_NOW).probability
    )


def test_stop_recovers_nothing(scorer):
    """STOP is a disposition, not a recovery channel."""
    for reason in FailureReason:
        assert base_rate(reason, ActionType.STOP) == 0.0


# ---------------------------------------------------------------------------
# Monotonicity (Requirement 9.8)
# ---------------------------------------------------------------------------


def test_probability_falls_as_attempt_count_rises(scorer):
    """Requirement 9.8."""
    probabilities = [
        scorer.predict(context_with(attempt_count=count), ActionType.RETRY_LATER).probability
        for count in (0, 1, 2, 3, 4)
    ]
    assert probabilities == sorted(probabilities, reverse=True)
    assert probabilities[0] > probabilities[-1]


def test_probability_rises_with_customer_success_rate(scorer):
    """Requirement 9.8."""
    probabilities = [
        scorer.predict(context_with(success_rate=rate), ActionType.RETRY_LATER).probability
        for rate in (0.10, 0.50, 0.90, 1.00)
    ]
    assert probabilities == sorted(probabilities)
    assert probabilities[0] < probabilities[-1]


def test_subscriber_scores_at_least_as_high(scorer):
    subscriber = scorer.predict(context_with(subscriber=True), ActionType.RETRY_LATER).probability
    non_subscriber = scorer.predict(
        context_with(subscriber=False), ActionType.RETRY_LATER
    ).probability
    assert subscriber >= non_subscriber


# ---------------------------------------------------------------------------
# Recovery history influence
# ---------------------------------------------------------------------------


def test_previously_failed_action_scores_lower(scorer):
    plain = scorer.predict(context_with(), ActionType.RETRY_LATER).probability
    penalised = scorer.predict(
        context_with(failed=frozenset({ActionType.RETRY_LATER})), ActionType.RETRY_LATER
    ).probability
    assert penalised < plain


def test_previously_succeeded_action_scores_higher(scorer):
    plain = scorer.predict(context_with(), ActionType.SEND_PAYMENT_LINK).probability
    rewarded = scorer.predict(
        context_with(succeeded=frozenset({ActionType.SEND_PAYMENT_LINK})),
        ActionType.SEND_PAYMENT_LINK,
    ).probability
    assert rewarded > plain


def test_previous_failure_outweighs_previous_success(scorer):
    """A failure on this payment is stronger evidence than a success elsewhere."""
    both = scorer.predict(
        context_with(
            succeeded=frozenset({ActionType.RETRY_LATER}),
            failed=frozenset({ActionType.RETRY_LATER}),
        ),
        ActionType.RETRY_LATER,
    ).probability
    plain = scorer.predict(context_with(), ActionType.RETRY_LATER).probability
    assert both < plain


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def test_confidence_is_highest_for_a_well_known_case(scorer):
    result = scorer.predict(context_with(attempt_count=1), ActionType.RETRY_LATER)
    assert result.confidence == pytest.approx(1.0)


def test_confidence_drops_without_customer_history(scorer):
    known = scorer.predict(context_with(history_available=True), ActionType.RETRY_LATER).confidence
    unknown = scorer.predict(
        context_with(history_available=False), ActionType.RETRY_LATER
    ).confidence
    assert unknown < known


def test_confidence_drops_for_an_unknown_cause(scorer):
    known = scorer.predict(context_with(), ActionType.RETRY_LATER).confidence
    unknown = scorer.predict(
        context_with(reason=FailureReason.UNKNOWN), ActionType.ESCALATE_HUMAN
    ).confidence
    assert unknown < known


def test_confidence_drops_after_many_attempts(scorer):
    few = scorer.predict(context_with(attempt_count=1), ActionType.RETRY_LATER).confidence
    many = scorer.predict(context_with(attempt_count=5), ActionType.RETRY_LATER).confidence
    assert many < few


def test_confidence_is_independent_of_probability(scorer):
    """Confidence measures information, not optimism."""
    context = context_with()
    high = scorer.predict(context, ActionType.RETRY_LATER)
    low = scorer.predict(context, ActionType.RETRY_NOW)
    assert high.probability > low.probability
    assert high.confidence == low.confidence


# ---------------------------------------------------------------------------
# Explanation
# ---------------------------------------------------------------------------


def test_explanation_anchors_on_the_base_rate(scorer):
    """Requirement 9.6."""
    result = scorer.predict(context_with(), ActionType.RETRY_LATER)
    assert result.explanation[0].name == "base_rate"
    assert result.explanation[0].influence == pytest.approx(
        BASE_RATE[FailureReason.BANK_TIMEOUT][ActionType.RETRY_LATER]
    )


def test_explanation_is_ordered_by_influence(scorer):
    """Requirement 9.6: most influential multiplier first."""
    result = scorer.predict(context_with(attempt_count=4), ActionType.RETRY_LATER)
    multipliers = result.explanation[1:]
    deviations = [abs(factor.influence - 1.0) for factor in multipliers]
    assert deviations == sorted(deviations, reverse=True)


def test_explanation_covers_every_multiplier(scorer):
    result = scorer.predict(context_with(), ActionType.RETRY_LATER)
    names = {factor.name for factor in result.explanation}
    assert names == {
        "base_rate",
        "attempt_count",
        "customer_success_rate",
        "subscription",
        "recovery_history",
    }


def test_explanation_text_is_readable(scorer):
    text = scorer.predict(context_with(), ActionType.RETRY_LATER).explanation_text()
    assert "base_rate" in text
    assert "attempt_count" in text


def test_explanation_serialises(scorer):
    payload = scorer.predict(context_with(), ActionType.RETRY_LATER).to_dict()
    assert payload["model_version"] == "deterministic-scorer-v1"
    assert isinstance(payload["explanation"], list)
    assert set(payload["explanation"][0]) == {"name", "value", "influence", "description"}


# ---------------------------------------------------------------------------
# The design's worked example
# ---------------------------------------------------------------------------


def test_worked_example_reproduces_the_documented_probabilities(scorer):
    """The numbers quoted in the design walkthrough.

    Bank timeout, attempt 1, customer success rate 0.94, active subscriber:
    base x 0.75 x 1.264 x 1.05, rounded to three decimals.
    """
    context = context_with(
        reason=FailureReason.BANK_TIMEOUT, attempt_count=1, success_rate=0.94, subscriber=True
    )

    assert scorer.predict(context, ActionType.RETRY_NOW).probability == pytest.approx(0.348)
    assert scorer.predict(context, ActionType.RETRY_LATER).probability == pytest.approx(0.776)
    assert scorer.predict(context, ActionType.SEND_PAYMENT_LINK).probability == pytest.approx(0.547)


def test_probability_is_rounded_to_three_decimals(scorer):
    """Keeps stored values, audit metadata, and ERV arithmetic in exact agreement."""
    probability = scorer.predict(context_with(), ActionType.RETRY_LATER).probability
    assert probability == round(probability, 3)


def test_no_machine_learning_library_is_imported():
    """Requirement 9.3."""
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "app" / "ml" / "deterministic_scorer.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not ({"sklearn", "numpy", "joblib", "pandas", "torch"} & imported)
