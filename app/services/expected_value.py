"""Expected recovery value.

The single implementation of the expected-recovery-value formula
(Requirement 10.4). Every other component obtains values by calling this module, so
the definition of "how much is this action worth" exists in exactly one place and
can be improved without a hunt through the codebase.

    expected_recovery_value =
        recovery_probability x payment_amount
        - intervention_cost
        - customer_friction_penalty

All arithmetic is in integer minor units (paise for INR). The full breakdown is
returned, not just the total, because the breakdown is what makes a recovery
decision reviewable: a judge can see the gross opportunity, what it cost to chase,
and what it cost the customer's patience.

This formula is why the system optimises for recovered revenue rather than retry
count. A cheap action with a poor probability loses to an expensive action with a
good one whenever the gross difference exceeds the cost difference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import ActionType


@dataclass(frozen=True)
class ExpectedValueBreakdown:
    """Complete expected-recovery-value arithmetic for one candidate action.

    Every monetary field is an integer in minor units.
    """

    action: ActionType
    recovery_probability: float
    payment_amount: int
    gross_expected_recovery: int
    intervention_cost: int
    customer_friction_penalty: int
    expected_recovery_value: int

    @property
    def total_cost(self) -> int:
        """Everything deducted from the gross opportunity."""
        return self.intervention_cost + self.customer_friction_penalty

    @property
    def is_worth_attempting(self) -> bool:
        """Whether the action is expected to net any revenue at all."""
        return self.expected_recovery_value > 0

    def to_dict(self) -> dict[str, Any]:
        """Serialized form stored on the recovery action and in audit metadata."""
        return {
            "action": self.action.value,
            "recovery_probability": self.recovery_probability,
            "payment_amount": self.payment_amount,
            "gross_expected_recovery": self.gross_expected_recovery,
            "intervention_cost": self.intervention_cost,
            "customer_friction_penalty": self.customer_friction_penalty,
            "expected_recovery_value": self.expected_recovery_value,
        }


class ExpectedRecoveryCalculator:
    """Values a candidate recovery action in money."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def calculate(
        self,
        *,
        amount: int,
        probability: float,
        action: ActionType,
    ) -> ExpectedValueBreakdown:
        """Value one candidate action (Requirement 10.1, 10.2).

        Costs come from configuration with documented defaults, so tuning the
        economics never requires a code change (Requirement 10.5).
        """
        intervention_cost = self._settings.intervention_cost(action)
        friction_penalty = self._settings.friction_penalty(action)

        gross = round(probability * amount)
        expected = gross - intervention_cost - friction_penalty

        return ExpectedValueBreakdown(
            action=action,
            recovery_probability=probability,
            payment_amount=int(amount),
            gross_expected_recovery=int(gross),
            intervention_cost=int(intervention_cost),
            customer_friction_penalty=int(friction_penalty),
            expected_recovery_value=int(expected),
        )

    def intervention_cost(self, action: ActionType) -> int:
        """Configured intervention cost for an action, in minor units."""
        return self._settings.intervention_cost(action)

    def friction_penalty(self, action: ActionType) -> int:
        """Configured customer friction penalty for an action, in minor units."""
        return self._settings.friction_penalty(action)


__all__ = ["ExpectedRecoveryCalculator", "ExpectedValueBreakdown"]
