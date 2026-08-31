"""Revenue risk detection.

One detection path serves every failure reason (Requirement 5.1). Checkout
abandonment and subscription failure are not special cases here: they are failure
reasons on ordinary payments, and the only place that branches per reason is the
candidate generator.

Detection is idempotent. Asking twice about the same failed payment reuses the
open case rather than opening a second one, so a demo operator can call
``/payments/{id}/fail`` repeatedly without accumulating duplicate work
(Requirement 5.3).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.enums import AuditEventType, CaseState, FailureReason, PaymentStatus, WorkflowStage
from app.core.logging import get_logger
from app.db.base import new_id
from app.models import Payment, RecoveryCase
from app.services.audit_service import AuditService

logger = get_logger("risk")


@dataclass(frozen=True)
class RiskAssessment:
    """Whether a payment puts revenue at risk, and why."""

    at_risk: bool
    reason: str
    amount_at_risk: int
    failure_reason: FailureReason | None


class RiskDetector:
    """Decides whether a payment represents revenue at risk."""

    def __init__(self, session: Session, clock: VirtualClock, audit: AuditService) -> None:
        self._session = session
        self._clock = clock
        self._audit = audit

    # -- assessment --------------------------------------------------------

    def assess(self, payment: Payment) -> RiskAssessment:
        """Classify a payment without writing anything (Requirement 5.1, 5.5)."""
        if payment.status in PaymentStatus.successful():
            return RiskAssessment(
                at_risk=False,
                reason=(
                    f"Payment status is {payment.status.value}; revenue was captured, "
                    "so there is nothing to recover."
                ),
                amount_at_risk=0,
                failure_reason=None,
            )

        if payment.status not in PaymentStatus.unsuccessful():
            return RiskAssessment(
                at_risk=False,
                reason=(
                    f"Payment status is {payment.status.value}; the payment has not yet "
                    "reached an unsuccessful state."
                ),
                amount_at_risk=0,
                failure_reason=None,
            )

        # An unsuccessful payment with no recorded cause is still revenue at risk;
        # the diagnosis engine resolves the cause to UNKNOWN and the policy engine
        # routes it to a human.
        resolved = payment.failure_reason or FailureReason.UNKNOWN
        return RiskAssessment(
            at_risk=True,
            reason=(
                f"Payment status is {payment.status.value} with cause {resolved.value}; "
                f"{payment.amount} {payment.currency} minor units are at risk."
            ),
            amount_at_risk=int(payment.amount),
            failure_reason=resolved,
        )

    # -- case management ---------------------------------------------------

    def find_open_case(self, payment_id: str) -> RecoveryCase | None:
        """Return this payment's non-terminal case, if one exists."""
        statement = (
            select(RecoveryCase)
            .where(RecoveryCase.payment_id == payment_id)
            .where(RecoveryCase.state.not_in(tuple(CaseState.terminal())))
            .order_by(RecoveryCase.created_at.desc(), RecoveryCase.case_id.desc())
        )
        return self._session.execute(statement).scalars().first()

    def detect_and_open_case(
        self, payment: Payment, *, case_id: str | None = None
    ) -> RecoveryCase | None:
        """Open (or reuse) a recovery case for an at-risk payment.

        Returns ``None`` when the payment is not at risk.

        ``case_id`` lets the seeded scenario generator assign stable identifiers so
        that reseeding with the same seed reproduces the same rows
        (Requirement 21.3). Left unset, an identifier is generated.
        """
        assessment = self.assess(payment)

        if not assessment.at_risk:
            logger.debug("payment %s not at risk: %s", payment.payment_id, assessment.reason)
            return None

        existing = self.find_open_case(payment.payment_id)
        if existing is not None:
            logger.debug(
                "reusing open case %s for payment %s", existing.case_id, payment.payment_id
            )
            return existing

        now = self._clock.now()
        case = RecoveryCase(
            case_id=case_id or new_id("case"),
            payment_id=payment.payment_id,
            state=CaseState.DETECTED,
            amount_at_risk=assessment.amount_at_risk,
            diagnosis=None,
            terminal_outcome=None,
            created_at=now,
            updated_at=now,
        )
        self._session.add(case)
        self._session.flush()

        self._audit.record(
            case_id=case.case_id,
            payment_id=payment.payment_id,
            stage=WorkflowStage.DETECTION,
            event_type=AuditEventType.REVENUE_RISK_DETECTED,
            message=(
                f"Revenue at risk: {assessment.amount_at_risk} {payment.currency} minor units "
                f"on payment {payment.payment_id} ({assessment.failure_reason.value})."
            ),
            metadata={
                "payment_id": payment.payment_id,
                "amount_at_risk": assessment.amount_at_risk,
                "currency": payment.currency,
                "failure_reason": assessment.failure_reason.value,
                "payment_status": payment.status.value,
                "attempt_count": payment.attempt_count,
                "payment_method": payment.payment_method.value,
                "detection_reason": assessment.reason,
            },
        )

        logger.info(
            "revenue risk detected | case=%s | payment=%s | at_risk=%s | reason=%s",
            case.case_id,
            payment.payment_id,
            assessment.amount_at_risk,
            assessment.failure_reason.value,
        )
        return case

    def get_case(self, case_id: str) -> RecoveryCase:
        """Return a case by id, or raise ``RecordNotFound``."""
        from app.core.errors import RecordNotFound

        case = self._session.get(RecoveryCase, case_id)
        if case is None:
            raise RecordNotFound("RecoveryCase", case_id)
        return case
