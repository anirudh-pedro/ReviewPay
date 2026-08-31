"""Payment and attempt persistence.

All payment state changes funnel through this service, which is what lets the
outcome verifier trust the database as the single source of truth about whether
revenue was recovered.

A note on customer history: ``historical_*`` counters on ``Customer`` describe the
customer's record **prior to** the payment under consideration. This service does
not mutate them as payments fail and recover. Facts about the payment in flight
come from ``Payment.attempt_count`` and the attempt rows, which the context
builder exposes separately. Keeping the two apart avoids double-counting a payment
that fails and is later recovered, and keeps the scoring feature
``customer_success_rate`` meaning one stable thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.clock import VirtualClock
from app.core.enums import (
    ActionType,
    FailureReason,
    PaymentMethod,
    PaymentStatus,
    SubscriptionStatus,
)
from app.core.errors import RecordNotFound
from app.core.logging import get_logger
from app.db.base import new_id
from app.models import Customer, Payment, PaymentAttempt

logger = get_logger("payments")

#: Provenance recorded on attempts that did not come from a recovery action.
SOURCE_CHECKOUT = "checkout"
SOURCE_SUBSCRIPTION = "subscription_charge"
SOURCE_RECOVERY = "recovery_action"

#: Failure reasons whose attempts originate from a subscription charge rather
#: than an interactive checkout.
_SUBSCRIPTION_REASONS = frozenset({FailureReason.SUBSCRIPTION_FAILURE})


@dataclass(frozen=True)
class PaymentPage:
    """A page of payments plus the total matching count."""

    items: list[Payment]
    total: int
    limit: int
    offset: int


def attempt_source(reason: FailureReason | None) -> str:
    """Where an attempt originated (Requirement 4.4).

    Provenance is carried on the payment and attempt records rather than on a
    separate revenue-event table.
    """
    if reason in _SUBSCRIPTION_REASONS:
        return SOURCE_SUBSCRIPTION
    return SOURCE_CHECKOUT


class PaymentService:
    """Create, fail, read, and record attempts against payments."""

    def __init__(self, session: Session, clock: VirtualClock) -> None:
        self._session = session
        self._clock = clock

    # -- customers ---------------------------------------------------------

    def ensure_customer(self, customer_id: str | None) -> Customer:
        """Return the named customer, creating a synthetic one when absent.

        Lets ``POST /payments/simulate`` produce a demonstrable at-risk payment in
        a single call.
        """
        if customer_id:
            customer = self._session.get(Customer, customer_id)
            if customer is not None:
                return customer
            return self._create_customer(customer_id)
        return self._create_customer(new_id("cust"))

    def _create_customer(self, customer_id: str) -> Customer:
        now = self._clock.now()
        customer = Customer(
            customer_id=customer_id,
            historical_payment_count=18,
            successful_payment_count=17,
            failed_payment_count=1,
            historical_success_rate=0.94,
            average_transaction_value=400_000,
            subscription_status=SubscriptionStatus.ACTIVE,
            meta={"generated": True},
            is_synthetic=True,
            name=None,
            created_at=now,
            updated_at=now,
        )
        self._session.add(customer)
        self._session.flush()
        return customer

    # -- creation ----------------------------------------------------------

    def create_payment(
        self,
        *,
        amount: int,
        currency: str = "INR",
        payment_method: PaymentMethod = PaymentMethod.UPI,
        status: PaymentStatus = PaymentStatus.CREATED,
        failure_reason: FailureReason | None = None,
        customer_id: str | None = None,
        merchant_id: str = "merch_demo",
        metadata: dict[str, Any] | None = None,
        payment_id: str | None = None,
    ) -> Payment:
        """Create a synthetic payment (Requirement 4.1).

        When the requested status is unsuccessful, the corresponding attempt is
        recorded and ``attempt_count`` starts at one, so the payment is
        immediately a valid input to risk detection.
        """
        customer = self.ensure_customer(customer_id)
        now = self._clock.now()

        starts_unsuccessful = status in PaymentStatus.unsuccessful()
        resolved_reason = failure_reason if starts_unsuccessful else None

        payment = Payment(
            payment_id=payment_id or new_id("pay"),
            customer_id=customer.customer_id,
            amount=int(amount),
            currency=currency,
            payment_method=payment_method,
            status=status,
            attempt_count=1 if starts_unsuccessful or status == PaymentStatus.SUCCEEDED else 0,
            failure_reason=resolved_reason,
            merchant_id=merchant_id,
            meta=metadata or {},
            is_synthetic=True,
            created_at=now,
            updated_at=now,
        )
        self._session.add(payment)
        self._session.flush()

        if starts_unsuccessful or status == PaymentStatus.SUCCEEDED:
            self._add_attempt(
                payment=payment,
                status=status,
                failure_reason=resolved_reason,
                source=attempt_source(resolved_reason),
                provider_response={"simulated": True, "origin": "create_payment"},
            )

        self._session.commit()
        logger.info(
            "payment created | %s | %s %s | status=%s",
            payment.payment_id,
            payment.amount,
            payment.currency,
            payment.status.value,
        )
        return payment

    # -- failure -----------------------------------------------------------

    def fail_payment(self, payment_id: str, failure_reason: FailureReason) -> Payment:
        """Fail a payment and record the attempt (Requirement 4.2)."""
        payment = self.get_payment(payment_id)

        payment.status = PaymentStatus.FAILED
        payment.failure_reason = failure_reason
        payment.attempt_count += 1
        payment.updated_at = self._clock.now()

        self._add_attempt(
            payment=payment,
            status=PaymentStatus.FAILED,
            failure_reason=failure_reason,
            source=attempt_source(failure_reason),
            provider_response={"simulated": True, "origin": "fail_payment"},
        )

        self._session.commit()
        logger.info(
            "payment failed | %s | reason=%s | attempt=%s",
            payment.payment_id,
            failure_reason.value,
            payment.attempt_count,
        )
        return payment

    # -- attempts ----------------------------------------------------------

    def record_recovery_attempt(
        self,
        *,
        payment: Payment,
        status: PaymentStatus,
        action: ActionType,
        failure_reason: FailureReason | None = None,
        provider_response: dict[str, Any] | None = None,
    ) -> PaymentAttempt:
        """Record an attempt produced by a recovery action.

        Used by the action executor. The attempt carries the action that caused
        it, which is how the context builder learns what has already been tried.
        """
        payment.attempt_count += 1
        payment.status = status
        payment.updated_at = self._clock.now()
        if status in PaymentStatus.successful():
            payment.failure_reason = None
        elif failure_reason is not None:
            payment.failure_reason = failure_reason

        attempt = self._add_attempt(
            payment=payment,
            status=status,
            failure_reason=None if status in PaymentStatus.successful() else failure_reason,
            source=SOURCE_RECOVERY,
            action_type=action,
            provider_response=provider_response or {},
        )
        self._session.flush()
        return attempt

    def _add_attempt(
        self,
        *,
        payment: Payment,
        status: PaymentStatus,
        failure_reason: FailureReason | None,
        source: str,
        action_type: ActionType | None = None,
        provider_response: dict[str, Any] | None = None,
        attempted_at: datetime | None = None,
    ) -> PaymentAttempt:
        attempt = PaymentAttempt(
            attempt_id=new_id("att"),
            payment_id=payment.payment_id,
            attempt_number=payment.attempt_count,
            status=status,
            failure_reason=failure_reason,
            action_type=action_type,
            provider_response=provider_response or {},
            source=source,
            attempted_at=attempted_at or self._clock.now(),
        )
        self._session.add(attempt)
        self._session.flush()
        return attempt

    # -- reads -------------------------------------------------------------

    def get_payment(self, payment_id: str) -> Payment:
        """Return one payment, or raise ``RecordNotFound`` (Requirement 4.4)."""
        payment = self._session.get(Payment, payment_id)
        if payment is None:
            raise RecordNotFound("Payment", payment_id)
        return payment

    def get_payment_with_attempts(self, payment_id: str) -> Payment:
        """Return one payment with its attempt history eagerly loaded."""
        statement = (
            select(Payment)
            .where(Payment.payment_id == payment_id)
            .options(selectinload(Payment.attempts))
        )
        payment = self._session.execute(statement).scalar_one_or_none()
        if payment is None:
            raise RecordNotFound("Payment", payment_id)
        return payment

    def list_payments(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: PaymentStatus | None = None,
    ) -> PaymentPage:
        """Return a page of payments, newest first (Requirement 4.5)."""
        conditions = []
        if status is not None:
            conditions.append(Payment.status == status)

        total_statement = select(func.count()).select_from(Payment)
        items_statement = select(Payment).order_by(Payment.created_at.desc(), Payment.payment_id)

        for condition in conditions:
            total_statement = total_statement.where(condition)
            items_statement = items_statement.where(condition)

        total = int(self._session.execute(total_statement).scalar_one())
        items = list(
            self._session.execute(items_statement.limit(limit).offset(offset)).scalars().all()
        )
        return PaymentPage(items=items, total=total, limit=limit, offset=offset)

    def list_at_risk_payments(self) -> list[Payment]:
        """Every payment whose status puts revenue at risk."""
        statement = (
            select(Payment)
            .where(Payment.status.in_(tuple(PaymentStatus.unsuccessful())))
            .order_by(Payment.created_at, Payment.payment_id)
        )
        return list(self._session.execute(statement).scalars().all())
