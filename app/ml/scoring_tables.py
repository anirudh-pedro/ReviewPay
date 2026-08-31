"""Scoring constants for the deterministic recovery predictor.

============================================================================
SYNTHETIC DEMONSTRATION VALUES
============================================================================
Every number in this module is invented for a hackathon simulation. None of it is
measured from real payment traffic, and no accuracy claim about the real world can
be derived from it. Phase 1 replaces this table with coefficients learned from a
generated dataset; the numbers there will be synthetic too.
============================================================================

The table is declarative on purpose. A reviewer can read the entire scoring policy
in one screen, and a demo can explain any probability by pointing at a row.

Design intent encoded here, which the tests pin down:

- ``RETRY_LATER`` beats ``RETRY_NOW`` for a transient, time-dependent failure.
  Waiting is the lever for a bank timeout, not attempt count.
- ``CHANGE_PAYMENT_METHOD`` beats ``RETRY_NOW`` for an expired card by a wide
  margin, because retrying a dead instrument cannot work.
- ``STOP`` recovers nothing, so its rate is exactly zero.
"""

from __future__ import annotations

from app.core.enums import ActionType, FailureReason

#: Baseline recovery rate per (failure reason, action). SYNTHETIC VALUES.
BASE_RATE: dict[FailureReason, dict[ActionType, float]] = {
    FailureReason.BANK_TIMEOUT: {
        ActionType.RETRY_NOW: 0.35,
        ActionType.RETRY_LATER: 0.78,
        ActionType.SEND_PAYMENT_LINK: 0.55,
        ActionType.CHANGE_PAYMENT_METHOD: 0.45,
        ActionType.SEND_REMINDER: 0.25,
        ActionType.ESCALATE_HUMAN: 0.30,
        ActionType.STOP: 0.0,
    },
    FailureReason.NETWORK_ERROR: {
        ActionType.RETRY_NOW: 0.55,
        ActionType.RETRY_LATER: 0.70,
        ActionType.SEND_PAYMENT_LINK: 0.48,
        ActionType.CHANGE_PAYMENT_METHOD: 0.40,
        ActionType.SEND_REMINDER: 0.22,
        ActionType.ESCALATE_HUMAN: 0.30,
        ActionType.STOP: 0.0,
    },
    FailureReason.INSUFFICIENT_FUNDS: {
        ActionType.RETRY_NOW: 0.12,
        ActionType.RETRY_LATER: 0.45,
        ActionType.SEND_PAYMENT_LINK: 0.40,
        ActionType.SEND_REMINDER: 0.35,
        ActionType.CHANGE_PAYMENT_METHOD: 0.38,
        ActionType.ESCALATE_HUMAN: 0.28,
        ActionType.STOP: 0.0,
    },
    FailureReason.EXPIRED_CARD: {
        # Retrying an expired card cannot succeed; the rate reflects that.
        ActionType.RETRY_NOW: 0.05,
        ActionType.RETRY_LATER: 0.05,
        ActionType.CHANGE_PAYMENT_METHOD: 0.72,
        ActionType.SEND_PAYMENT_LINK: 0.58,
        ActionType.SEND_REMINDER: 0.30,
        ActionType.ESCALATE_HUMAN: 0.30,
        ActionType.STOP: 0.0,
    },
    FailureReason.CHECKOUT_ABANDONMENT: {
        ActionType.RETRY_NOW: 0.08,
        ActionType.RETRY_LATER: 0.10,
        ActionType.SEND_PAYMENT_LINK: 0.42,
        ActionType.SEND_REMINDER: 0.30,
        ActionType.CHANGE_PAYMENT_METHOD: 0.15,
        ActionType.ESCALATE_HUMAN: 0.20,
        ActionType.STOP: 0.0,
    },
    FailureReason.SUBSCRIPTION_FAILURE: {
        ActionType.RETRY_NOW: 0.25,
        ActionType.RETRY_LATER: 0.60,
        ActionType.SEND_PAYMENT_LINK: 0.48,
        ActionType.SEND_REMINDER: 0.35,
        ActionType.CHANGE_PAYMENT_METHOD: 0.42,
        ActionType.ESCALATE_HUMAN: 0.28,
        ActionType.STOP: 0.0,
    },
    FailureReason.UNKNOWN: {
        # Nothing automated is trustworthy without knowing the cause.
        ActionType.RETRY_NOW: 0.10,
        ActionType.RETRY_LATER: 0.12,
        ActionType.SEND_PAYMENT_LINK: 0.18,
        ActionType.SEND_REMINDER: 0.12,
        ActionType.CHANGE_PAYMENT_METHOD: 0.15,
        ActionType.ESCALATE_HUMAN: 0.25,
        ActionType.STOP: 0.0,
    },
}

#: Used when a (reason, action) pair is absent from the table above.
FALLBACK_BASE_RATE = 0.20

# --- Multiplicative adjustments ---------------------------------------------

#: Each recorded attempt multiplies the rate by this. Repeated failure on the same
#: payment is evidence against the next attempt working.
ATTEMPT_DECAY = 0.75

#: Customer reliability maps a success rate in [0, 1] onto this multiplier range.
CUSTOMER_FACTOR_FLOOR = 0.70
CUSTOMER_FACTOR_SPAN = 0.60  # floor + span => 1.30 at a perfect success rate

#: Subscribers have a standing billing relationship, which helps slightly.
SUBSCRIPTION_FACTOR = 1.05
NO_SUBSCRIPTION_FACTOR = 1.00

#: This action already recovered a payment for this customer.
PREVIOUSLY_SUCCEEDED_FACTOR = 1.15

#: This action was already tried on this payment and did not work.
PREVIOUSLY_FAILED_FACTOR = 0.60

NEUTRAL_FACTOR = 1.00

#: Probabilities are clamped away from 0 and 1: nothing here is certain.
MIN_PROBABILITY = 0.02
MAX_PROBABILITY = 0.97

#: Probabilities are rounded to this many decimals so that stored values, audit
#: metadata, and demo arithmetic all agree exactly.
PROBABILITY_DECIMALS = 3

# --- Confidence -------------------------------------------------------------
# Confidence describes how much the scorer knows, not how high the probability is.

CONFIDENCE_BASE = 0.50
CONFIDENCE_CUSTOMER_HISTORY = 0.20
CONFIDENCE_FEW_ATTEMPTS = 0.15
CONFIDENCE_KNOWN_CAUSE = 0.15
CONFIDENCE_FEW_ATTEMPTS_THRESHOLD = 2


def base_rate(reason: FailureReason, action: ActionType) -> float:
    """Baseline rate for a (reason, action) pair, with a documented fallback."""
    return BASE_RATE.get(reason, {}).get(action, FALLBACK_BASE_RATE)
