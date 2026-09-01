"""Bounded, auditable historical recovery summaries.

This read-only service aggregates independently verified outcomes.  It excludes
the current case explicitly, so a payment can never contribute its own label to a
prediction or explanation.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ActionType, FailureReason, SubscriptionStatus
from app.models import Customer, Payment, RecoveryAction, RecoveryCase, RecoveryOutcome


@dataclass(frozen=True)
class HistoricalRecoveryInsight:
    """Success statistics for a transparent, bounded historical cohort."""

    action: str
    failure_reason: str
    customer_segment: str
    samples: int
    successes: int
    success_rate: float | None
    window_limit: int
    excludes_case_id: str | None
    source: str = "verified_synthetic_recovery_outcomes"


class HistoricalRecoveryLearning:
    """Query verified outcomes only; never update model state online."""

    def __init__(self, session: Session, *, max_outcomes: int = 120) -> None:
        self._session = session
        self._max_outcomes = max(max_outcomes, 1)

    def insight(
        self,
        *,
        action: ActionType,
        failure_reason: FailureReason,
        subscription_status: SubscriptionStatus,
        exclude_case_id: str | None = None,
    ) -> HistoricalRecoveryInsight:
        """Return fixed-window action/failure/segment statistics."""

        statement = (
            select(RecoveryAction, RecoveryOutcome, RecoveryCase, Payment, Customer)
            .join(RecoveryOutcome, RecoveryOutcome.action_id == RecoveryAction.action_id)
            .join(RecoveryCase, RecoveryCase.case_id == RecoveryAction.case_id)
            .join(Payment, Payment.payment_id == RecoveryAction.payment_id)
            .outerjoin(Customer, Customer.customer_id == Payment.customer_id)
            .where(RecoveryAction.action_type == action)
            .order_by(RecoveryOutcome.verification_timestamp.desc(), RecoveryAction.action_id.desc())
            .limit(self._max_outcomes)
        )
        rows = self._session.execute(statement).all()
        matches = []
        for row_action, outcome, case, _payment, customer in rows:
            if exclude_case_id and case.case_id == exclude_case_id:
                continue
            diagnosis = case.diagnosis or {}
            reason = diagnosis.get("failure_reason") or (
                outcome.failure_reason.value if outcome.failure_reason else FailureReason.UNKNOWN.value
            )
            segment = (
                customer.subscription_status.value
                if customer is not None
                else SubscriptionStatus.NONE.value
            )
            if reason == failure_reason.value and segment == subscription_status.value:
                matches.append(bool(outcome.recovered))

        successes = sum(matches)
        samples = len(matches)
        return HistoricalRecoveryInsight(
            action=action.value,
            failure_reason=failure_reason.value,
            customer_segment=subscription_status.value,
            samples=samples,
            successes=successes,
            success_rate=round(successes / samples, 4) if samples else None,
            window_limit=self._max_outcomes,
            excludes_case_id=exclude_case_id,
        )


__all__ = ["HistoricalRecoveryInsight", "HistoricalRecoveryLearning"]
