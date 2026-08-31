"""Expected recovery value tests (Requirement 10.1-10.5, 25.7)."""

from __future__ import annotations

import pytest

from app.core.enums import ActionType
from app.services.expected_value import ExpectedRecoveryCalculator


@pytest.fixture
def calculator(settings) -> ExpectedRecoveryCalculator:
    return ExpectedRecoveryCalculator(settings)


# ---------------------------------------------------------------------------
# The worked example (Requirement 10.3, 25.7)
# ---------------------------------------------------------------------------


def test_worked_example_from_the_specification(calculator):
    """INR 10,000 at 0.72 with INR 20 cost and INR 100 friction gives INR 7,080.

    Expressed in minor units: 1,000,000 x 0.72 = 720,000 gross, minus 2,000 minus
    10,000, giving exactly 708,000.
    """
    breakdown = calculator.calculate(
        amount=1_000_000,
        probability=0.72,
        action=ActionType.RETRY_LATER,
    )

    assert breakdown.payment_amount == 1_000_000
    assert breakdown.recovery_probability == 0.72
    assert breakdown.gross_expected_recovery == 720_000
    assert breakdown.intervention_cost == 2_000
    assert breakdown.customer_friction_penalty == 10_000
    assert breakdown.expected_recovery_value == 708_000


def test_worked_example_totals_are_self_consistent(calculator):
    breakdown = calculator.calculate(
        amount=1_000_000, probability=0.72, action=ActionType.RETRY_LATER
    )
    assert (
        breakdown.expected_recovery_value
        == breakdown.gross_expected_recovery
        - breakdown.intervention_cost
        - breakdown.customer_friction_penalty
    )
    assert breakdown.total_cost == 12_000


# ---------------------------------------------------------------------------
# Breakdown completeness
# ---------------------------------------------------------------------------


def test_breakdown_exposes_every_required_field(calculator):
    """Requirement 10.2."""
    payload = calculator.calculate(
        amount=500_000, probability=0.5, action=ActionType.RETRY_NOW
    ).to_dict()

    assert {
        "recovery_probability",
        "payment_amount",
        "gross_expected_recovery",
        "intervention_cost",
        "customer_friction_penalty",
        "expected_recovery_value",
    }.issubset(payload)


def test_every_monetary_field_is_an_integer(calculator):
    """Requirement 10.1: minor units, never floats."""
    breakdown = calculator.calculate(
        amount=333_333, probability=0.333, action=ActionType.SEND_PAYMENT_LINK
    )
    for value in (
        breakdown.payment_amount,
        breakdown.gross_expected_recovery,
        breakdown.intervention_cost,
        breakdown.customer_friction_penalty,
        breakdown.expected_recovery_value,
    ):
        assert isinstance(value, int)


def test_breakdown_is_immutable(calculator):
    breakdown = calculator.calculate(amount=100, probability=0.5, action=ActionType.RETRY_NOW)
    with pytest.raises(Exception):
        breakdown.expected_recovery_value = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Arithmetic properties
# ---------------------------------------------------------------------------


def test_expected_value_rises_strictly_with_probability(calculator):
    """Requirement 10.1: monotonicity with costs held fixed."""
    values = [
        calculator.calculate(
            amount=1_000_000, probability=probability, action=ActionType.RETRY_LATER
        ).expected_recovery_value
        for probability in (0.1, 0.3, 0.5, 0.7, 0.9)
    ]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_expected_value_rises_with_amount(calculator):
    values = [
        calculator.calculate(
            amount=amount, probability=0.5, action=ActionType.RETRY_LATER
        ).expected_recovery_value
        for amount in (100_000, 500_000, 1_000_000)
    ]
    assert values == sorted(values)


def test_zero_probability_yields_a_negative_value_equal_to_costs(calculator):
    """Chasing a hopeless payment costs money."""
    breakdown = calculator.calculate(
        amount=1_000_000, probability=0.0, action=ActionType.RETRY_LATER
    )
    assert breakdown.gross_expected_recovery == 0
    assert breakdown.expected_recovery_value == -12_000
    assert breakdown.is_worth_attempting is False


def test_certain_recovery_nets_the_amount_less_costs(calculator):
    breakdown = calculator.calculate(
        amount=1_000_000, probability=1.0, action=ActionType.RETRY_LATER
    )
    assert breakdown.gross_expected_recovery == 1_000_000
    assert breakdown.expected_recovery_value == 988_000
    assert breakdown.is_worth_attempting is True


def test_small_amount_can_be_uneconomic_to_chase(calculator):
    """A cheap payment is not worth an expensive intervention."""
    breakdown = calculator.calculate(
        amount=5_000, probability=0.9, action=ActionType.ESCALATE_HUMAN
    )
    assert breakdown.expected_recovery_value < 0


def test_gross_is_rounded_to_the_nearest_minor_unit(calculator):
    breakdown = calculator.calculate(
        amount=333_333, probability=0.333, action=ActionType.STOP
    )
    assert breakdown.gross_expected_recovery == round(0.333 * 333_333)


def test_stop_has_no_cost(calculator):
    breakdown = calculator.calculate(amount=1_000_000, probability=0.0, action=ActionType.STOP)
    assert breakdown.intervention_cost == 0
    assert breakdown.customer_friction_penalty == 0
    assert breakdown.expected_recovery_value == 0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_costs_are_defined_for_every_action(calculator):
    """Requirement 10.5."""
    for action in ActionType:
        breakdown = calculator.calculate(amount=100_000, probability=0.5, action=action)
        assert breakdown.intervention_cost >= 0
        assert breakdown.customer_friction_penalty >= 0


def test_costs_come_from_configuration(settings):
    """Requirement 10.5: tuning economics needs no code change."""
    from app.core.config import Settings

    custom = Settings(
        _env_file=None,
        intervention_cost_minor={"RETRY_LATER": 9_000},
        friction_penalty_minor={"RETRY_LATER": 1_000},
    )
    breakdown = ExpectedRecoveryCalculator(custom).calculate(
        amount=1_000_000, probability=0.72, action=ActionType.RETRY_LATER
    )

    assert breakdown.intervention_cost == 9_000
    assert breakdown.customer_friction_penalty == 1_000
    assert breakdown.expected_recovery_value == 720_000 - 9_000 - 1_000


def test_unconfigured_action_falls_back_to_documented_defaults(calculator):
    from app.core.config import DEFAULT_INTERVENTION_COST_MINOR, Settings

    partial = Settings(_env_file=None, intervention_cost_minor={"RETRY_NOW": 1})
    calculator_partial = ExpectedRecoveryCalculator(partial)

    assert calculator_partial.intervention_cost(ActionType.RETRY_NOW) == 1
    assert (
        calculator_partial.intervention_cost(ActionType.SEND_REMINDER)
        == DEFAULT_INTERVENTION_COST_MINOR["SEND_REMINDER"]
    )


def test_cost_accessors_match_the_breakdown(calculator):
    breakdown = calculator.calculate(
        amount=100_000, probability=0.5, action=ActionType.SEND_PAYMENT_LINK
    )
    assert calculator.intervention_cost(ActionType.SEND_PAYMENT_LINK) == breakdown.intervention_cost
    assert (
        calculator.friction_penalty(ActionType.SEND_PAYMENT_LINK)
        == breakdown.customer_friction_penalty
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_calculation_is_deterministic(calculator):
    first = calculator.calculate(amount=1_000_000, probability=0.72, action=ActionType.RETRY_LATER)
    second = calculator.calculate(amount=1_000_000, probability=0.72, action=ActionType.RETRY_LATER)
    assert first == second


def test_ordering_by_expected_value_prefers_the_better_action(calculator):
    """The core claim: optimise recovered revenue, not attempt count.

    RETRY_LATER costs more than RETRY_NOW, yet wins because its gross advantage
    exceeds the cost difference.
    """
    retry_now = calculator.calculate(
        amount=1_000_000, probability=0.348, action=ActionType.RETRY_NOW
    )
    retry_later = calculator.calculate(
        amount=1_000_000, probability=0.776, action=ActionType.RETRY_LATER
    )

    assert retry_later.intervention_cost > retry_now.intervention_cost
    assert retry_later.expected_recovery_value > retry_now.expected_recovery_value
    # The exact figures quoted in the design walkthrough.
    assert retry_now.expected_recovery_value == 345_500
    assert retry_later.expected_recovery_value == 764_000
