"""Outcome verification.

The component that makes "revenue recovered" a defensible claim rather than a
hopeful one.

It never asks the executor whether the action worked. It re-reads the persisted
payment and decides from that state alone (Requirement 15.2, 15.5). If a buggy,
optimistic, or outright lying executor reports success while the payment is still
failed, this reports ``recovered=False`` and the recovered total stays honest. That
is the whole reason the component is separate from execution.

Analytics sums recovered revenue from the rows this writes, and nothing else
(Requirement 15.7).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.enums import AuditEventType, PaymentStatus, WorkflowStage
from app.core.errors import RecordNotFound
from app.core.logging import get_logger
from app.db.base import new_id
from app.models import Payment, RecoveryAction, RecoveryOutcome
from app.services.audit_service import AuditService

logger = get_logger("verifier")


class OutcomeVerifier:
    """Independently verifies whether a recovery action recovered revenue."""

    def __init__(self, session: Session, clock: VirtualClock) -> None:
        self._session = session
        self._clock = clock

    def verify(
        self,
        action: RecoveryAction,
        previous_status: PaymentStatus,
        *,
        audit: AuditService | None = None,
        workflow_id: str | None = None,
    ) -> RecoveryOutcome:
        """Produce a verified outcome for an executed action (Requirement 15.1).

        ``previous_status`` is captured by the caller *before* execution, so the
        transition can be described even though the payment row has since changed.
        """
        payment = self._session.get(Payment, action.payment_id)
        if payment is None:
            raise RecordNotFound("Payment", action.payment_id)

        # Read the persisted state. This is the authority, not the execution result.
        new_status = payment.status

        recovered = (
            new_status in PaymentStatus.successful()
            and previous_status not in PaymentStatus.successful()
        )
        recovered_amount = int(payment.amount) if recovered else 0

        outcome = RecoveryOutcome(
            outcome_id=new_id("out"),
            action_id=action.action_id,
            previous_payment_status=previous_status,
            new_payment_status=new_status,
            recovered=recovered,
            recovered_amount=recovered_amount,
            failure_reason=None if recovered else payment.failure_reason,
            verification_timestamp=self._clock.now(),
        )
        self._session.add(outcome)
        self._session.flush()

        if audit is not None:
            self._audit(audit, action, outcome, payment, workflow_id)

        logger.info(
            "verify | %s | %s -> %s | recovered=%s amount=%s",
            payment.payment_id,
            previous_status.value,
            new_status.value,
            recovered,
            recovered_amount,
        )
        return outcome

    # -- audit -------------------------------------------------------------

    @staticmethod
    def _audit(
        audit: AuditService,
        action: RecoveryAction,
        outcome: RecoveryOutcome,
        payment: Payment,
        workflow_id: str | None,
    ) -> None:
        """Record verification, and revenue recovery when confirmed.

        Two events rather than one: ``OUTCOME_VERIFIED`` always fires so the trail
        shows that verification happened, and ``REVENUE_RECOVERED`` fires only when
        money was actually recovered. A reviewer can therefore count recovered
        revenue by counting one event type (Requirement 15.6).
        """
        audit.record(
            case_id=action.case_id,
            payment_id=action.payment_id,
            stage=WorkflowStage.VERIFICATION,
            event_type=AuditEventType.OUTCOME_VERIFIED,
            message=(
                f"Verified payment state after {action.action_type.value}: "
                f"{outcome.previous_payment_status.value} -> {outcome.new_payment_status.value}. "
                f"Recovered: {outcome.recovered}."
            ),
            metadata={
                "action_id": action.action_id,
                "action": action.action_type.value,
                "previous_payment_status": outcome.previous_payment_status.value,
                "new_payment_status": outcome.new_payment_status.value,
                "recovered": outcome.recovered,
                "recovered_amount": outcome.recovered_amount,
                "currency": payment.currency,
                "failure_reason": (
                    outcome.failure_reason.value if outcome.failure_reason else None
                ),
                "verification_basis": (
                    "Persisted payment status re-read after execution; the executor's "
                    "reported status was not used."
                ),
            },
            workflow_id=workflow_id,
        )

        if outcome.recovered:
            audit.record(
                case_id=action.case_id,
                payment_id=action.payment_id,
                stage=WorkflowStage.VERIFICATION,
                event_type=AuditEventType.REVENUE_RECOVERED,
                message=(
                    f"Recovered {outcome.recovered_amount} {payment.currency} minor units "
                    f"on payment {payment.payment_id} via {action.action_type.value}."
                ),
                metadata={
                    "action_id": action.action_id,
                    "action": action.action_type.value,
                    "recovered_amount": outcome.recovered_amount,
                    "currency": payment.currency,
                    "expected_recovery_value": action.expected_recovery_value,
                    "predicted_probability": action.estimated_probability,
                    "model_version": action.model_version,
                },
                workflow_id=workflow_id,
            )


__all__ = ["OutcomeVerifier"]
