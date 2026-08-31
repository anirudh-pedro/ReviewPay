"""Recovery context construction.

Every database read for one workflow run happens here, once. Downstream
components — diagnosis, candidate generation, scoring, valuation, ranking, policy —
receive a frozen ``RecoveryContext`` and never query models themselves
(Requirement 6.1, 6.5, 6.6). Two consequences worth stating:

- The decision path is testable without a database session.
- Repeated builds over unchanged rows produce identical features, which is the
  foundation of the system's reproducibility guarantee (Requirement 6.4).

Time-derived features come from the virtual clock and stored timestamps, never
from wall-clock time (Requirement 6.3).

``diagnosis`` is carried as a plain mapping rather than a typed object so that this
module has no import edge to ``diagnosis_engine``; the engines pass the typed
``Diagnosis`` alongside the context instead. Dependencies point one way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.enums import (
    ActionType,
    FailureReason,
    PaymentMethod,
    PaymentStatus,
    SubscriptionStatus,
)
from app.core.errors import RecordNotFound
from app.models import (
    Customer,
    Payment,
    PaymentAttempt,
    RecoveryAction,
    RecoveryCase,
    RecoveryOutcome,
)

# Neutral defaults used when a customer record is unavailable (Requirement 6.7).
NEUTRAL_SUCCESS_RATE = 0.5
NEUTRAL_AVERAGE_TRANSACTION_VALUE = 0


@dataclass(frozen=True)
class CustomerSnapshot:
    """A customer's history as it stood before the payment under consideration."""

    customer_id: str
    total_payments: int
    successful_payments: int
    failed_payments: int
    success_rate: float
    average_transaction_value: int
    subscription_status: SubscriptionStatus
    history_available: bool

    @property
    def is_subscriber(self) -> bool:
        return self.subscription_status in {
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
        }

    @classmethod
    def unavailable(cls, customer_id: str) -> "CustomerSnapshot":
        """Documented neutral defaults for a missing customer (Requirement 6.7)."""
        return cls(
            customer_id=customer_id,
            total_payments=0,
            successful_payments=0,
            failed_payments=0,
            success_rate=NEUTRAL_SUCCESS_RATE,
            average_transaction_value=NEUTRAL_AVERAGE_TRANSACTION_VALUE,
            subscription_status=SubscriptionStatus.NONE,
            history_available=False,
        )


@dataclass(frozen=True)
class RecoveryContext:
    """Everything the decision path needs about one at-risk payment."""

    # Identity
    case_id: str
    payment_id: str

    # Payment facts
    amount: int
    currency: str
    payment_method: PaymentMethod
    payment_status: PaymentStatus
    failure_reason: FailureReason
    attempt_count: int
    merchant_id: str

    # Customer facts
    customer: CustomerSnapshot

    # Time-derived facts
    transaction_hour: int
    days_since_previous_payment: int | None
    is_returning_customer: bool

    # Recovery history
    previous_recovery_attempt_count: int
    attempted_action_types: frozenset[ActionType]
    succeeded_action_types: frozenset[ActionType]
    failed_action_types: frozenset[ActionType]
    unsuccessful_outcome_count: int

    # Failure history for this payment
    failure_reason_history: tuple[FailureReason, ...]

    # Serialized diagnosis, once the diagnosis engine has run.
    diagnosis: dict[str, Any] | None = None

    # Scheduling
    scheduled_at: Any | None = None
    pending_action_id: str | None = None

    extras: dict[str, Any] = field(default_factory=dict)

    # -- derived features --------------------------------------------------

    def features(self) -> dict[str, Any]:
        """The flat feature projection consumed by the recovery predictor.

        Phase 1 extracts this into a dedicated fingerprint component; the decision
        engine does not change when it does, because it never reads features
        directly.
        """
        return {
            "payment_amount": self.amount,
            "payment_method": self.payment_method.value,
            "failure_reason": self.failure_reason.value,
            "attempt_count": self.attempt_count,
            "customer_success_rate": self.customer.success_rate,
            "customer_failed_payments": self.customer.failed_payments,
            "customer_total_payments": self.customer.total_payments,
            "customer_successful_payments": self.customer.successful_payments,
            "customer_average_transaction_value": self.customer.average_transaction_value,
            "subscription_status": self.customer.subscription_status.value,
            "subscription": self.customer.is_subscriber,
            "transaction_hour": self.transaction_hour,
            "is_returning_customer": self.is_returning_customer,
            "days_since_previous_payment": self.days_since_previous_payment,
            "customer_history_available": self.customer.history_available,
            "previous_recovery_attempt_count": self.previous_recovery_attempt_count,
            "attempted_action_types": sorted(item.value for item in self.attempted_action_types),
            "succeeded_action_types": sorted(item.value for item in self.succeeded_action_types),
            "failed_action_types": sorted(item.value for item in self.failed_action_types),
            "unsuccessful_outcome_count": self.unsuccessful_outcome_count,
        }

    def has_previously_succeeded(self, action: ActionType) -> bool:
        """True when this action already recovered a payment for this customer."""
        return action in self.succeeded_action_types

    def has_previously_failed(self, action: ActionType) -> bool:
        """True when this action was already tried on this payment and did not work."""
        return action in self.failed_action_types


class RecoveryContextBuilder:
    """Assembles a ``RecoveryContext`` from persisted records."""

    def __init__(self, session: Session, clock: VirtualClock) -> None:
        self._session = session
        self._clock = clock

    def build(self, case: RecoveryCase) -> RecoveryContext:
        """Build the context for a case in a single pass (Requirement 6.1)."""
        payment = self._session.get(Payment, case.payment_id)
        if payment is None:
            raise RecordNotFound("Payment", case.payment_id)

        customer = self._session.get(Customer, payment.customer_id)
        snapshot = (
            self._snapshot(customer)
            if customer is not None
            else CustomerSnapshot.unavailable(payment.customer_id)
        )

        attempts = self._attempts(payment.payment_id)
        actions = self._actions(payment.payment_id)

        attempted: set[ActionType] = set()
        succeeded: set[ActionType] = set()
        failed: set[ActionType] = set()
        unsuccessful_outcomes = 0
        executed_count = 0
        pending_action_id: str | None = None
        scheduled_at = None

        for action in actions:
            if action.executed_at is not None:
                attempted.add(action.action_type)
                executed_count += 1

            outcome = action.outcome
            if outcome is not None:
                if outcome.recovered:
                    succeeded.add(action.action_type)
                else:
                    failed.add(action.action_type)
                    unsuccessful_outcomes += 1

            # A scheduled action that has not executed yet is the pending one.
            if action.scheduled_at is not None and action.executed_at is None:
                pending_action_id = action.action_id
                scheduled_at = action.scheduled_at

        # Actions previously recovered for this customer on *other* payments also
        # count as evidence that the channel works for them.
        succeeded |= self._customer_successful_action_types(
            payment.customer_id, exclude_payment_id=payment.payment_id
        )

        return RecoveryContext(
            case_id=case.case_id,
            payment_id=payment.payment_id,
            amount=int(payment.amount),
            currency=payment.currency,
            payment_method=payment.payment_method,
            payment_status=payment.status,
            failure_reason=payment.failure_reason or FailureReason.UNKNOWN,
            attempt_count=int(payment.attempt_count),
            merchant_id=payment.merchant_id,
            customer=snapshot,
            transaction_hour=payment.created_at.hour,
            days_since_previous_payment=self._days_since_previous_payment(payment),
            is_returning_customer=snapshot.total_payments > 0,
            previous_recovery_attempt_count=executed_count,
            attempted_action_types=frozenset(attempted),
            succeeded_action_types=frozenset(succeeded),
            failed_action_types=frozenset(failed),
            unsuccessful_outcome_count=unsuccessful_outcomes,
            failure_reason_history=tuple(
                attempt.failure_reason for attempt in attempts if attempt.failure_reason
            ),
            diagnosis=case.diagnosis,
            scheduled_at=scheduled_at,
            pending_action_id=pending_action_id,
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _snapshot(customer: Customer) -> CustomerSnapshot:
        return CustomerSnapshot(
            customer_id=customer.customer_id,
            total_payments=int(customer.historical_payment_count),
            successful_payments=int(customer.successful_payment_count),
            failed_payments=int(customer.failed_payment_count),
            success_rate=float(customer.historical_success_rate),
            average_transaction_value=int(customer.average_transaction_value),
            subscription_status=customer.subscription_status,
            history_available=True,
        )

    def _attempts(self, payment_id: str) -> list[PaymentAttempt]:
        statement = (
            select(PaymentAttempt)
            .where(PaymentAttempt.payment_id == payment_id)
            .order_by(PaymentAttempt.attempt_number, PaymentAttempt.attempt_id)
        )
        return list(self._session.execute(statement).scalars().all())

    def _actions(self, payment_id: str) -> list[RecoveryAction]:
        statement = (
            select(RecoveryAction)
            .where(RecoveryAction.payment_id == payment_id)
            .order_by(RecoveryAction.created_at, RecoveryAction.action_id)
        )
        return list(self._session.execute(statement).scalars().all())

    def _customer_successful_action_types(
        self, customer_id: str, *, exclude_payment_id: str
    ) -> set[ActionType]:
        """Action types that have recovered other payments for this customer."""
        statement = (
            select(RecoveryAction.action_type)
            .join(RecoveryOutcome, RecoveryOutcome.action_id == RecoveryAction.action_id)
            .join(Payment, Payment.payment_id == RecoveryAction.payment_id)
            .where(Payment.customer_id == customer_id)
            .where(RecoveryAction.payment_id != exclude_payment_id)
            .where(RecoveryOutcome.recovered.is_(True))
        )
        rows = self._session.execute(statement).scalars().all()
        return {row for row in rows if row is not None}

    def _days_since_previous_payment(self, payment: Payment) -> int | None:
        """Days between this payment and the customer's previous one.

        Derived from stored timestamps rather than wall-clock time; returns ``None``
        for a customer's first payment.
        """
        statement = (
            select(Payment.created_at)
            .where(Payment.customer_id == payment.customer_id)
            .where(Payment.payment_id != payment.payment_id)
            .where(Payment.created_at <= payment.created_at)
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        previous = self._session.execute(statement).scalars().first()
        if previous is None:
            return None
        return max((payment.created_at - previous).days, 0)
