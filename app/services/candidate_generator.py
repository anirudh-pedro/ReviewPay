"""Candidate recovery action generation.

This module is the **only** place in the decision path that branches on a specific
failure reason (Requirement 8.9). Risk detection, scoring, valuation, ranking, and
policy all stay reason-agnostic, which is what allows a new failure reason to be
supported by editing one table.

It generates candidates and nothing else: no scoring, no ranking, no selection
(Requirement 8.1). Choosing among candidates belongs to the decision engine.
"""

from __future__ import annotations

from app.core.enums import ActionType, FailureReason
from app.core.logging import get_logger
from app.services.context_builder import RecoveryContext
from app.services.diagnosis_engine import Diagnosis

logger = get_logger("candidates")

#: Plausible recovery actions per failure reason (Requirement 8.2-8.8).
#:
#: Declaration order is meaningful: it is the final tiebreak when two candidates
#: value identically, so these lists are ordered most-plausible-first.
CANDIDATES_BY_REASON: dict[FailureReason, tuple[ActionType, ...]] = {
    # Transient infrastructure fault: the same instrument can still work.
    FailureReason.BANK_TIMEOUT: (
        ActionType.RETRY_NOW,
        ActionType.RETRY_LATER,
        ActionType.SEND_PAYMENT_LINK,
    ),
    # The instrument cannot succeed. Retrying it is pointless, so every candidate
    # either changes the instrument or hands off.
    FailureReason.EXPIRED_CARD: (
        ActionType.CHANGE_PAYMENT_METHOD,
        ActionType.SEND_PAYMENT_LINK,
        ActionType.ESCALATE_HUMAN,
    ),
    # Balance-dependent: waiting is the lever, not attempt count.
    FailureReason.INSUFFICIENT_FUNDS: (
        ActionType.RETRY_LATER,
        ActionType.SEND_PAYMENT_LINK,
        ActionType.SEND_REMINDER,
    ),
    # No charge was attempted; recovery is an engagement problem.
    FailureReason.CHECKOUT_ABANDONMENT: (
        ActionType.SEND_REMINDER,
        ActionType.SEND_PAYMENT_LINK,
    ),
    FailureReason.NETWORK_ERROR: (
        ActionType.RETRY_NOW,
        ActionType.RETRY_LATER,
    ),
    FailureReason.SUBSCRIPTION_FAILURE: (
        ActionType.RETRY_LATER,
        ActionType.SEND_REMINDER,
        ActionType.SEND_PAYMENT_LINK,
    ),
    # Cause unknown: automated financial action is not safe.
    FailureReason.UNKNOWN: (
        ActionType.ESCALATE_HUMAN,
        ActionType.STOP,
    ),
}

#: Dispositions that stay available even after a previous attempt, because they
#: end the workflow rather than attempting a charge.
_NEVER_FILTERED = frozenset({ActionType.ESCALATE_HUMAN, ActionType.STOP})


class RecoveryActionCandidateGenerator:
    """Produces the set of plausible recovery actions for a diagnosis."""

    def generate(self, context: RecoveryContext, diagnosis: Diagnosis) -> list[ActionType]:
        """Return candidate actions, never a selection (Requirement 8.1).

        Actions that already failed on this payment are dropped, provided at least
        one alternative survives (Requirement 8.10). That single rule is what moves
        an expired-card case from ``RETRY_NOW`` to ``CHANGE_PAYMENT_METHOD`` on its
        second run, without anything else needing to know why.
        """
        base = CANDIDATES_BY_REASON.get(
            diagnosis.failure_reason, CANDIDATES_BY_REASON[FailureReason.UNKNOWN]
        )

        viable = [
            action
            for action in base
            if action in _NEVER_FILTERED or not context.has_previously_failed(action)
        ]

        # Never hand back an empty list: an exhausted case still needs a
        # disposition, and the policy engine is what stops it.
        candidates = viable or list(base)

        logger.debug(
            "candidates for %s | %s",
            diagnosis.failure_reason.value,
            [action.value for action in candidates],
        )
        return list(candidates)

    @staticmethod
    def candidates_for(reason: FailureReason) -> tuple[ActionType, ...]:
        """The unfiltered candidate tuple for a reason. Useful for demos and docs."""
        return CANDIDATES_BY_REASON.get(reason, CANDIDATES_BY_REASON[FailureReason.UNKNOWN])


__all__ = ["CANDIDATES_BY_REASON", "RecoveryActionCandidateGenerator"]
