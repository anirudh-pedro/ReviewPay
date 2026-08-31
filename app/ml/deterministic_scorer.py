"""Deterministic recovery probability scoring.

Phase 0's ``RecoveryPredictor``. A pure function of the recovery context and the
candidate action: no model file, no network, no randomness, no ML library
(Requirement 9.3, 9.4).

    probability = clamp(
        base_rate(reason, action)
          x attempt_decay
          x customer_factor
          x subscription_factor
          x history_factor
    )

Every multiplier is reported back in ``PredictionResult.explanation``, ordered by
how much it moved the score, so the number is never a black box even in Phase 0.

Rounding to three decimals is deliberate. It makes stored probabilities, audit
metadata, and the expected-recovery-value arithmetic agree exactly, which is what
lets a demo read ``0.776 x 1,000,000 = 776,000`` and be literally correct.

This module contains no per-failure-reason branching; the reason only ever indexes
the declarative table in ``scoring_tables`` (Requirement 9.9).
"""

from __future__ import annotations

from app.core.enums import ActionType
from app.core.logging import get_logger
from app.ml.predictor import PredictionResult, ScoringFactor
from app.ml.scoring_tables import (
    ATTEMPT_DECAY,
    CONFIDENCE_BASE,
    CONFIDENCE_CUSTOMER_HISTORY,
    CONFIDENCE_FEW_ATTEMPTS,
    CONFIDENCE_FEW_ATTEMPTS_THRESHOLD,
    CONFIDENCE_KNOWN_CAUSE,
    CUSTOMER_FACTOR_FLOOR,
    CUSTOMER_FACTOR_SPAN,
    MAX_PROBABILITY,
    MIN_PROBABILITY,
    NEUTRAL_FACTOR,
    NO_SUBSCRIPTION_FACTOR,
    PREVIOUSLY_FAILED_FACTOR,
    PREVIOUSLY_SUCCEEDED_FACTOR,
    PROBABILITY_DECIMALS,
    SUBSCRIPTION_FACTOR,
    base_rate,
)
from app.services.context_builder import RecoveryContext

logger = get_logger("predictor")

#: Features this scorer consumes. Reported on every prediction.
FEATURES_USED: tuple[str, ...] = (
    "failure_reason",
    "attempt_count",
    "customer_success_rate",
    "subscription",
    "succeeded_action_types",
    "failed_action_types",
)

#: The cause is unresolved when the diagnosis could not name it.
_UNKNOWN_CAUSE = "UNKNOWN"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class DeterministicRecoveryScorer:
    """Transparent, reproducible recovery probability estimation."""

    MODEL_VERSION = "deterministic-scorer-v1"

    @property
    def model_version(self) -> str:
        return self.MODEL_VERSION

    def predict(self, context: RecoveryContext, action: ActionType) -> PredictionResult:
        """Score one candidate action (Requirement 9.1, 9.2)."""
        anchor = base_rate(context.failure_reason, action)

        attempt_factor = ATTEMPT_DECAY**max(context.attempt_count, 0)
        customer_factor = CUSTOMER_FACTOR_FLOOR + CUSTOMER_FACTOR_SPAN * _clamp(
            context.customer.success_rate, 0.0, 1.0
        )
        subscription_factor = (
            SUBSCRIPTION_FACTOR if context.customer.is_subscriber else NO_SUBSCRIPTION_FACTOR
        )
        history_factor = self._history_factor(context, action)

        raw = anchor * attempt_factor * customer_factor * subscription_factor * history_factor
        probability = round(
            _clamp(raw, MIN_PROBABILITY, MAX_PROBABILITY), PROBABILITY_DECIMALS
        )

        result = PredictionResult(
            probability=probability,
            confidence=self._confidence(context),
            model_version=self.MODEL_VERSION,
            features_used=FEATURES_USED,
            explanation=self._explain(
                action=action,
                context=context,
                anchor=anchor,
                attempt_factor=attempt_factor,
                customer_factor=customer_factor,
                subscription_factor=subscription_factor,
                history_factor=history_factor,
            ),
        )

        logger.debug(
            "predict | %s | %s | p=%.3f conf=%.2f",
            context.payment_id,
            action.value,
            result.probability,
            result.confidence,
        )
        return result

    # -- components --------------------------------------------------------

    @staticmethod
    def _history_factor(context: RecoveryContext, action: ActionType) -> float:
        """Reward a channel that has worked; penalise one that has not.

        A previous failure on *this* payment is stronger evidence than a previous
        success elsewhere, so it takes precedence.
        """
        if context.has_previously_failed(action):
            return PREVIOUSLY_FAILED_FACTOR
        if context.has_previously_succeeded(action):
            return PREVIOUSLY_SUCCEEDED_FACTOR
        return NEUTRAL_FACTOR

    @staticmethod
    def _confidence(context: RecoveryContext) -> float:
        """How much the scorer knows about this case (Requirement 9.1).

        Confidence is about information available, not about the probability being
        high. Phase 0 records it; Phase 1 routes on it.
        """
        score = CONFIDENCE_BASE
        if context.customer.history_available:
            score += CONFIDENCE_CUSTOMER_HISTORY
        if context.attempt_count <= CONFIDENCE_FEW_ATTEMPTS_THRESHOLD:
            score += CONFIDENCE_FEW_ATTEMPTS
        if context.failure_reason.value != _UNKNOWN_CAUSE:
            score += CONFIDENCE_KNOWN_CAUSE
        return round(_clamp(score, 0.0, 1.0), 2)

    @staticmethod
    def _explain(
        *,
        action: ActionType,
        context: RecoveryContext,
        anchor: float,
        attempt_factor: float,
        customer_factor: float,
        subscription_factor: float,
        history_factor: float,
    ) -> tuple[ScoringFactor, ...]:
        """Report the reasoning, most influential multiplier first."""
        base = ScoringFactor(
            name="base_rate",
            value=f"{context.failure_reason.value}/{action.value}",
            influence=anchor,
            description=(
                f"Baseline recovery rate for {action.value} against "
                f"{context.failure_reason.value} (synthetic demonstration value)."
            ),
        )

        multipliers = [
            ScoringFactor(
                name="attempt_count",
                value=context.attempt_count,
                influence=attempt_factor,
                description=(
                    f"{context.attempt_count} prior attempt(s) recorded; each one "
                    "reduces the expected chance of the next succeeding."
                ),
            ),
            ScoringFactor(
                name="customer_success_rate",
                value=round(context.customer.success_rate, 3),
                influence=customer_factor,
                description=(
                    "Customer's historical payment success rate"
                    + ("" if context.customer.history_available else " (unavailable, neutral default)")
                    + "."
                ),
            ),
            ScoringFactor(
                name="subscription",
                value=context.customer.subscription_status.value,
                influence=subscription_factor,
                description=(
                    "An active billing relationship slightly improves recovery odds."
                    if context.customer.is_subscriber
                    else "No active subscription; no adjustment applied."
                ),
            ),
            ScoringFactor(
                name="recovery_history",
                value=(
                    "previously_failed"
                    if context.has_previously_failed(action)
                    else "previously_succeeded"
                    if context.has_previously_succeeded(action)
                    else "no_history"
                ),
                influence=history_factor,
                description=(
                    f"{action.value} already failed on this payment."
                    if context.has_previously_failed(action)
                    else f"{action.value} previously recovered a payment for this customer."
                    if context.has_previously_succeeded(action)
                    else f"No prior outcome recorded for {action.value}."
                ),
            ),
        ]

        # Order by how far each multiplier moved the score.
        multipliers.sort(key=lambda factor: abs(factor.influence - 1.0), reverse=True)
        return (base, *multipliers)


__all__ = ["FEATURES_USED", "DeterministicRecoveryScorer"]
