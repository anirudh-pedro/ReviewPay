"""Configurable policy rule set.

Every safety rule in the system lives here, as an ordered list of small objects.
Nothing in a route handler decides whether a recovery action is permitted
(Requirement 13.11), and tuning a threshold is a configuration change rather than a
code change (Requirement 13.2).

**Rule order is a safety decision, not an implementation detail.** Blocking rules
run before escalation rules, so a case that has exhausted its retries stops rather
than paging a human about a payment nobody should keep chasing. Within the blocking
group, cheaper structural checks (is this action even valid here?) precede
history-dependent ones.

Evaluation stops at the first rule that returns a verdict (Requirement 13.12), so
each rule only needs to describe its own concern.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.config import Settings
from app.core.enums import ActionType, FailureReason, PaymentStatus, PolicyOutcome
from app.services.context_builder import RecoveryContext
from app.services.decision_engine import RecoveryDecision


@dataclass(frozen=True)
class PolicyResult:
    """A policy verdict, the rule that produced it, and why."""

    outcome: PolicyOutcome
    rule_id: str
    reason: str

    @property
    def approved(self) -> bool:
        return self.outcome is PolicyOutcome.APPROVED

    @property
    def blocked(self) -> bool:
        return self.outcome is PolicyOutcome.BLOCKED

    @property
    def escalated(self) -> bool:
        return self.outcome is PolicyOutcome.ESCALATED

    def to_dict(self) -> dict[str, str]:
        return {
            "outcome": self.outcome.value,
            "rule_id": self.rule_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PolicyInput:
    """Everything a rule may consider.

    Passed as one object rather than as positional arguments so that adding an
    input in a later phase does not change every rule signature.
    """

    context: RecoveryContext
    decision: RecoveryDecision
    settings: Settings
    supported_actions: frozenset[ActionType]

    @property
    def action(self) -> ActionType:
        return self.decision.selected_action


@runtime_checkable
class PolicyRule(Protocol):
    """A single safety rule. Returns ``None`` when it has no objection."""

    rule_id: str

    def evaluate(self, data: PolicyInput) -> PolicyResult | None: ...


# ---------------------------------------------------------------------------
# Blocking rules
# ---------------------------------------------------------------------------


class InvalidPaymentStateRule:
    """Reject an action that makes no sense for the payment's current state.

    Recovering an already-successful payment would double-charge a customer, so
    this runs first (Requirement 13.6).
    """

    rule_id = "invalid_payment_state"

    def evaluate(self, data: PolicyInput) -> PolicyResult | None:
        action = data.action

        # Escalating or stopping is valid from any state: neither moves money.
        if action in ActionType.terminal_actions():
            return None

        if data.context.payment_status not in PaymentStatus.unsuccessful():
            return PolicyResult(
                outcome=PolicyOutcome.BLOCKED,
                rule_id=self.rule_id,
                reason=(
                    f"Payment is in state {data.context.payment_status.value}, which is not a "
                    f"valid state from which to perform {action.value}. Only an unsuccessful "
                    "payment may be recovered."
                ),
            )
        return None


class UnsupportedActionRule:
    """Reject an action the configured executor cannot perform.

    Guards the seam where a provider-backed executor supports fewer actions than
    the simulator (Requirement 13.7).
    """

    rule_id = "unsupported_action"

    def evaluate(self, data: PolicyInput) -> PolicyResult | None:
        if data.action not in data.supported_actions:
            return PolicyResult(
                outcome=PolicyOutcome.BLOCKED,
                rule_id=self.rule_id,
                reason=(
                    f"Action {data.action.value} is not supported by the configured action "
                    "executor, so it cannot be performed."
                ),
            )
        return None


class RetryLimitRule:
    """Stop retrying a payment once the automatic retry budget is spent.

    Bounds how hard the system will push one payment (Requirement 13.3).
    """

    rule_id = "retry_limit_reached"

    def evaluate(self, data: PolicyInput) -> PolicyResult | None:
        limit = data.settings.max_automatic_retries
        attempts = data.context.attempt_count

        if data.action in ActionType.retry_actions() and attempts >= limit:
            return PolicyResult(
                outcome=PolicyOutcome.BLOCKED,
                rule_id=self.rule_id,
                reason=(
                    f"Payment has {attempts} recorded attempt(s), reaching the configured "
                    f"maximum of {limit} automatic retries. {data.action.value} would exceed "
                    "the retry budget, so recovery stops."
                ),
            )
        return None


class RecoveryBudgetRule:
    """Stop *any* automatic recovery once the payment's attempt budget is spent.

    ``RetryLimitRule`` bounds retries. This bounds recovery as a whole, and exists
    because bounding only retries turned out to be bypassable: once the retry
    budget was exhausted, a case could keep going through non-retry channels
    (``SEND_PAYMENT_LINK``, then ``SEND_REMINDER``), driving ``attempt_count`` well
    past the configured maximum. Each of those is an automatic action against a
    payment the system has already agreed to stop pushing.

    Terminal dispositions are exempt: escalating or stopping moves no money and is
    how an exhausted case is supposed to end.
    """

    rule_id = "recovery_budget_exhausted"

    def evaluate(self, data: PolicyInput) -> PolicyResult | None:
        if data.action in ActionType.terminal_actions():
            return None

        limit = data.settings.max_automatic_retries
        attempts = data.context.attempt_count

        if attempts >= limit:
            return PolicyResult(
                outcome=PolicyOutcome.BLOCKED,
                rule_id=self.rule_id,
                reason=(
                    f"Payment has {attempts} recorded attempt(s), exhausting the recovery "
                    f"budget of {limit} automatic attempts. {data.action.value} is an "
                    "automatic recovery action and may not bypass the exhausted budget, so "
                    "recovery stops."
                ),
            )
        return None


class RepeatedFailureRule:
    """Stop a case that keeps failing verification, whatever the action.

    The backstop that guarantees termination: without it, a case could cycle
    through non-retry channels indefinitely (Requirement 13.8).
    """

    rule_id = "repeated_failure_limit"

    def evaluate(self, data: PolicyInput) -> PolicyResult | None:
        limit = data.settings.repeated_failure_limit
        failures = data.context.unsuccessful_outcome_count

        if failures >= limit:
            return PolicyResult(
                outcome=PolicyOutcome.BLOCKED,
                rule_id=self.rule_id,
                reason=(
                    f"{failures} recovery attempt(s) on this payment have been verified as "
                    f"unsuccessful, reaching the configured limit of {limit}. Further "
                    "automated recovery is unlikely to succeed, so recovery stops."
                ),
            )
        return None


# ---------------------------------------------------------------------------
# Escalation rules
# ---------------------------------------------------------------------------


class UnknownFailureRule:
    """Refuse to act automatically on a cause nobody understands.

    Escalates when a human is available, blocks otherwise (Requirement 13.5).
    """

    rule_id = "unknown_failure"

    def evaluate(self, data: PolicyInput) -> PolicyResult | None:
        if data.context.failure_reason is not FailureReason.UNKNOWN:
            return None

        if data.settings.allow_human_escalation:
            return PolicyResult(
                outcome=PolicyOutcome.ESCALATED,
                rule_id=self.rule_id,
                reason=(
                    "The failure cause is UNKNOWN. Automated recovery is not safe without "
                    "knowing why the payment failed, so the case is escalated for human "
                    "review."
                ),
            )

        return PolicyResult(
            outcome=PolicyOutcome.BLOCKED,
            rule_id=self.rule_id,
            reason=(
                "The failure cause is UNKNOWN and human escalation is disabled, so recovery "
                "stops rather than acting on an unexplained failure."
            ),
        )


class HighValueTransactionRule:
    """Hand large payments to a human instead of recovering them automatically.

    The blast radius of a wrong decision scales with the amount
    (Requirement 13.4).
    """

    rule_id = "high_value_transaction"

    def evaluate(self, data: PolicyInput) -> PolicyResult | None:
        threshold = data.settings.high_value_escalation_threshold
        amount = data.context.amount

        if amount <= threshold:
            return None

        if data.settings.allow_human_escalation:
            return PolicyResult(
                outcome=PolicyOutcome.ESCALATED,
                rule_id=self.rule_id,
                reason=(
                    f"Payment amount {amount} {data.context.currency} minor units exceeds the "
                    f"automatic recovery threshold of {threshold}. A human approves recovery "
                    "at this value rather than the system acting alone."
                ),
            )

        return PolicyResult(
            outcome=PolicyOutcome.BLOCKED,
            rule_id=self.rule_id,
            reason=(
                f"Payment amount {amount} exceeds the automatic recovery threshold of "
                f"{threshold} and human escalation is disabled, so recovery stops."
            ),
        )


# ---------------------------------------------------------------------------
# Default
# ---------------------------------------------------------------------------

DEFAULT_APPROVE_RULE_ID = "default_approve"


def default_approval(data: PolicyInput) -> PolicyResult:
    """The verdict when no rule objected."""
    return PolicyResult(
        outcome=PolicyOutcome.APPROVED,
        rule_id=DEFAULT_APPROVE_RULE_ID,
        reason=(
            f"{data.action.value} is within all configured safety limits: "
            f"{data.context.attempt_count} of {data.settings.max_automatic_retries} retries used, "
            f"amount {data.context.amount} within the automatic threshold of "
            f"{data.settings.high_value_escalation_threshold}, and the failure cause "
            f"({data.context.failure_reason.value}) is known."
        ),
    )


#: Evaluation order. Blocking rules first, then escalation rules.
#:
#: ``RetryLimitRule`` precedes ``RecoveryBudgetRule`` so that a blocked retry is
#: still attributed to the more specific rule; the budget rule then catches every
#: other automatic action, which is what makes the limit unbypassable.
DEFAULT_RULES: tuple[PolicyRule, ...] = (
    InvalidPaymentStateRule(),
    UnsupportedActionRule(),
    RetryLimitRule(),
    RecoveryBudgetRule(),
    RepeatedFailureRule(),
    UnknownFailureRule(),
    HighValueTransactionRule(),
)

#: Rule identifiers in evaluation order. Useful for documentation and assertions.
RULE_ORDER: tuple[str, ...] = tuple(rule.rule_id for rule in DEFAULT_RULES) + (
    DEFAULT_APPROVE_RULE_ID,
)


__all__ = [
    "DEFAULT_APPROVE_RULE_ID",
    "DEFAULT_RULES",
    "RULE_ORDER",
    "HighValueTransactionRule",
    "InvalidPaymentStateRule",
    "PolicyInput",
    "PolicyResult",
    "PolicyRule",
    "RecoveryBudgetRule",
    "RepeatedFailureRule",
    "RetryLimitRule",
    "UnknownFailureRule",
    "UnsupportedActionRule",
    "default_approval",
]
