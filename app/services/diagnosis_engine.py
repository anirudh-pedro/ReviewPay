"""Failure diagnosis.

Answers "why is this revenue at risk?" in structured form, so that candidate
generation and scoring respond to the actual cause rather than to a generic retry
policy.

The engine is a pure function of the context (Requirement 7.4): it reads no
database and writes nothing. Persisting the diagnosis on the case and recording
``DIAGNOSIS_COMPLETED`` belong to the workflow, which keeps this component
substitutable — Phase 1 replaces ``RuleBasedDiagnosisEngine`` with an LLM-backed
implementation behind the same Protocol and nothing else changes
(Requirement 7.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.core.enums import FailureCategory, FailureReason, Transience
from app.services.context_builder import RecoveryContext


@dataclass(frozen=True)
class Diagnosis:
    """Why a payment failed, and what that implies for recovery."""

    failure_reason: FailureReason
    category: FailureCategory
    transience: Transience
    requires_escalation: bool
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        """Serialized form for persistence on the case and for audit metadata."""
        return {
            "failure_reason": self.failure_reason.value,
            "category": self.category.value,
            "transience": self.transience.value,
            "requires_escalation": self.requires_escalation,
            "explanation": self.explanation,
        }

    @property
    def is_transient(self) -> bool:
        return self.transience is Transience.TRANSIENT

    @property
    def permits_human_handling(self) -> bool:
        """Whether escalating to a human is a sensible disposition for this cause."""
        return self.category is not FailureCategory.UNKNOWN or self.requires_escalation


@runtime_checkable
class DiagnosisEngine(Protocol):
    """Produces a structured diagnosis from a recovery context."""

    def diagnose(self, context: RecoveryContext) -> Diagnosis: ...


# Classification table (Requirement 7.2). Each entry names the category, the
# transience, and whether the cause requires a human by default.
_CLASSIFICATION: dict[FailureReason, tuple[FailureCategory, Transience, bool, str]] = {
    FailureReason.BANK_TIMEOUT: (
        FailureCategory.TRANSIENT,
        Transience.TRANSIENT,
        False,
        "The issuing bank did not respond in time. This is transient infrastructure "
        "behaviour, so the same instrument usually succeeds on a later attempt.",
    ),
    FailureReason.NETWORK_ERROR: (
        FailureCategory.TRANSIENT,
        Transience.TRANSIENT,
        False,
        "A network fault interrupted the authorisation. Nothing about the customer or "
        "the instrument has changed, so a repeat attempt is reasonable.",
    ),
    FailureReason.EXPIRED_CARD: (
        FailureCategory.CUSTOMER_ACTION,
        Transience.PERSISTENT,
        False,
        "The card is expired. Retrying the same instrument cannot succeed; recovery "
        "requires the customer to supply different payment details.",
    ),
    FailureReason.INSUFFICIENT_FUNDS: (
        FailureCategory.TIME_DEPENDENT,
        Transience.TRANSIENT,
        False,
        "The account lacked sufficient balance. Whether a retry succeeds depends on "
        "when the customer's balance is replenished, so timing matters more than "
        "attempt count.",
    ),
    FailureReason.CHECKOUT_ABANDONMENT: (
        FailureCategory.ENGAGEMENT,
        Transience.PERSISTENT,
        False,
        "The customer left checkout before authorising. No charge was attempted, so "
        "recovery depends on re-engaging the customer rather than on retrying.",
    ),
    FailureReason.SUBSCRIPTION_FAILURE: (
        FailureCategory.ENGAGEMENT,
        Transience.TRANSIENT,
        False,
        "A scheduled subscription charge did not complete. Recovery depends on the "
        "instrument becoming chargeable again or on prompting the customer.",
    ),
    FailureReason.UNKNOWN: (
        FailureCategory.UNKNOWN,
        Transience.UNKNOWN,
        True,
        "The failure cause could not be determined. Automated recovery is not safe "
        "without knowing why the payment failed, so this case needs a human.",
    ),
}


class RuleBasedDiagnosisEngine:
    """Deterministic, table-driven diagnosis.

    Phase 0's implementation. The table is explicit on purpose: a reviewer can
    read the whole policy in one screen, and a demo can explain any verdict.
    """

    version = "rule-based-diagnosis-v1"

    def diagnose(self, context: RecoveryContext) -> Diagnosis:
        """Classify the failure recorded on the context (Requirement 7.1)."""
        reason = context.failure_reason

        if reason not in _CLASSIFICATION:
            # An unrecognised member resolves to UNKNOWN rather than crashing, so a
            # future enum addition degrades to human handling instead of failing a
            # live run (Requirement 7.3).
            reason = FailureReason.UNKNOWN

        category, transience, requires_escalation, explanation = _CLASSIFICATION[reason]

        return Diagnosis(
            failure_reason=reason,
            category=category,
            transience=transience,
            requires_escalation=requires_escalation,
            explanation=self._contextualise(explanation, context),
        )

    @staticmethod
    def _contextualise(explanation: str, context: RecoveryContext) -> str:
        """Append the attempt history, which is what makes the text useful in a demo."""
        if context.attempt_count > 1:
            explanation = (
                f"{explanation} This payment has already been attempted "
                f"{context.attempt_count} times."
            )
        if context.failed_action_types:
            tried = ", ".join(sorted(item.value for item in context.failed_action_types))
            explanation = f"{explanation} Previously unsuccessful recovery actions: {tried}."
        return explanation


__all__ = ["Diagnosis", "DiagnosisEngine", "RuleBasedDiagnosisEngine"]
