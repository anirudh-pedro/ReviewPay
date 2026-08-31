"""Synthetic scenario generation.

============================================================================
SYNTHETIC DEMONSTRATION DATA
Every customer, payment, and attempt produced here is invented. No real person,
card, or bank is involved, and no figure derived from this data describes real
payment behaviour.
============================================================================

Two responsibilities, deliberately separated:

- ``generate()`` populates a realistic background of customers and payments across
  all six failure reasons, so analytics and listing endpoints have something to
  show.
- ``generate_demo_scenarios()`` builds the four cases the demo and the end-to-end
  tests depend on, each constructed so its outcome is **guaranteed** rather than
  probable.

Determinism comes from two places (Requirement 21.3): identifiers are sequential
rather than random, and every simulated outcome is decided by the payment
simulator's scripted table or its seeded hash. Reseeding an empty database with the
same seed therefore reproduces the same rows and the same eventual outcomes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings, get_settings
from app.core.enums import FailureReason, PaymentMethod, PaymentStatus, SubscriptionStatus
from app.core.logging import get_logger
from app.models import Customer, Payment, PaymentAttempt, RecoveryCase
from app.services.audit_service import AuditService
from app.services.risk_detector import RiskDetector

logger = get_logger("seed")

SYNTHETIC_MARKER = "synthetic_demo_data"


@dataclass(frozen=True)
class DemoScenario:
    """One deterministic demonstration case."""

    key: str
    title: str
    narrative: str
    payment: Payment
    case: RecoveryCase
    expected_action: str
    expected_final_state: str
    requires_clock_advance: bool


@dataclass(frozen=True)
class SeedSummary:
    """What a seed run produced."""

    customers: int
    payments: int
    cases: int
    scenarios: tuple[DemoScenario, ...]


# Background population: (failure reason, payment method, amount in minor units).
_BACKGROUND_MIX: tuple[tuple[FailureReason, PaymentMethod, int], ...] = (
    (FailureReason.BANK_TIMEOUT, PaymentMethod.UPI, 249_900),
    (FailureReason.INSUFFICIENT_FUNDS, PaymentMethod.CARD, 189_900),
    (FailureReason.EXPIRED_CARD, PaymentMethod.CARD, 499_900),
    (FailureReason.NETWORK_ERROR, PaymentMethod.NETBANKING, 129_900),
    (FailureReason.CHECKOUT_ABANDONMENT, PaymentMethod.WALLET, 89_900),
    (FailureReason.SUBSCRIPTION_FAILURE, PaymentMethod.CARD, 79_900),
)


class ScenarioGenerator:
    """Creates synthetic customers, payments, and recovery cases."""

    def __init__(
        self,
        session: Session,
        clock: VirtualClock,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._settings = settings or get_settings()
        self._audit = AuditService(session, clock)
        self._detector = RiskDetector(session=session, clock=clock, audit=self._audit)
        # Seeded only for cosmetic variation (names, hours). Never for outcomes.
        self._rng = random.Random(self._settings.simulation_seed)

    # -- public API --------------------------------------------------------

    def generate(self, *, background_customers: int = 12) -> SeedSummary:
        """Populate the database with synthetic data (Requirement 21.1, 21.2)."""
        customers = self._background_customers(background_customers)
        payments = self._background_payments(customers)
        scenarios = self.generate_demo_scenarios()

        self._session.commit()

        summary = SeedSummary(
            customers=len(customers) + len(scenarios),
            payments=len(payments) + len(scenarios),
            cases=self._session.query(RecoveryCase).count(),
            scenarios=scenarios,
        )
        logger.info(
            "seeded | customers=%s payments=%s cases=%s scenarios=%s",
            summary.customers,
            summary.payments,
            summary.cases,
            len(summary.scenarios),
        )
        return summary

    def generate_demo_scenarios(self) -> tuple[DemoScenario, ...]:
        """Build the four guaranteed scenarios (Requirement 21.4-21.7)."""
        return (
            self._scenario_a(),
            self._scenario_b(),
            self._scenario_c(),
            self._scenario_d(),
        )

    # -- the four scenarios ------------------------------------------------

    def _scenario_a(self) -> DemoScenario:
        """A: BANK_TIMEOUT recovers through a delayed retry (Requirement 21.4).

        Guaranteed because ``(BANK_TIMEOUT, RETRY_LATER)`` is scripted to succeed,
        and RETRY_LATER wins on expected recovery value against RETRY_NOW.
        """
        customer = self._customer(
            key="a",
            name="Priya Sharma",
            total=18,
            failed=1,
            success_rate=0.94,
            subscription=SubscriptionStatus.ACTIVE,
            average=400_000,
        )
        payment, case = self._at_risk_payment(
            key="a",
            customer=customer,
            amount=1_000_000,  # INR 10,000.00
            method=PaymentMethod.UPI,
            reason=FailureReason.BANK_TIMEOUT,
            attempts=1,
        )
        return DemoScenario(
            key="A",
            title="Successful recovery through a delayed retry",
            narrative=(
                "A reliable customer's UPI payment hits a bank timeout. The cause is "
                "transient, so waiting is worth more than retrying immediately."
            ),
            payment=payment,
            case=case,
            expected_action="RETRY_LATER",
            expected_final_state="RECOVERED",
            requires_clock_advance=True,
        )

    def _scenario_b(self) -> DemoScenario:
        """B: INSUFFICIENT_FUNDS stops at the retry limit (Requirement 21.5).

        The payment arrives having already used its retry budget, which is exactly
        the state the retry-limit rule exists to catch. Retries against an empty
        balance are scripted to fail, so nothing can recover it by accident.
        """
        customer = self._customer(
            key="b",
            name="Rahul Mehta",
            total=6,
            failed=3,
            success_rate=0.50,
            subscription=SubscriptionStatus.NONE,
            average=180_000,
        )
        payment, case = self._at_risk_payment(
            key="b",
            customer=customer,
            amount=250_000,  # INR 2,500.00
            method=PaymentMethod.CARD,
            reason=FailureReason.INSUFFICIENT_FUNDS,
            attempts=self._settings.max_automatic_retries,
        )
        return DemoScenario(
            key="B",
            title="Recovery stopped by the retry limit",
            narrative=(
                "A card payment has already failed for insufficient funds as many times "
                "as policy allows. The system stops rather than chasing it further."
            ),
            payment=payment,
            case=case,
            expected_action="RETRY_LATER",
            expected_final_state="STOPPED",
            requires_clock_advance=False,
        )

    def _scenario_c(self) -> DemoScenario:
        """C: a high-value payment goes to a human (Requirement 21.6)."""
        customer = self._customer(
            key="c",
            name="Anita Desai",
            total=24,
            failed=2,
            success_rate=0.92,
            subscription=SubscriptionStatus.ACTIVE,
            average=2_500_000,
        )
        payment, case = self._at_risk_payment(
            key="c",
            customer=customer,
            amount=self._settings.high_value_escalation_threshold + 4_000_000,
            method=PaymentMethod.NETBANKING,
            reason=FailureReason.BANK_TIMEOUT,
            attempts=1,
        )
        return DemoScenario(
            key="C",
            title="High-value transaction escalated to a human",
            narrative=(
                "The amount exceeds the automatic recovery threshold. A person decides "
                "this one; the system executes nothing."
            ),
            payment=payment,
            case=case,
            expected_action="RETRY_LATER",
            expected_final_state="ESCALATED",
            requires_clock_advance=False,
        )

    def _scenario_d(self) -> DemoScenario:
        """D: EXPIRED_CARD recovers via a new instrument (Requirement 21.7).

        Guaranteed because retrying an expired card is scripted to fail while
        changing the instrument is scripted to succeed, and the scorer ranks
        CHANGE_PAYMENT_METHOD far above RETRY_NOW for this cause.
        """
        customer = self._customer(
            key="d",
            name="Vikram Iyer",
            total=31,
            failed=2,
            success_rate=0.94,
            subscription=SubscriptionStatus.ACTIVE,
            average=520_000,
        )
        payment, case = self._at_risk_payment(
            key="d",
            customer=customer,
            amount=600_000,  # INR 6,000.00
            method=PaymentMethod.CARD,
            reason=FailureReason.EXPIRED_CARD,
            attempts=1,
        )
        return DemoScenario(
            key="D",
            title="Alternative payment method recovery",
            narrative=(
                "The card on file has expired. Retrying it cannot work, so the system "
                "recovers the revenue through a different instrument."
            ),
            payment=payment,
            case=case,
            expected_action="CHANGE_PAYMENT_METHOD",
            expected_final_state="RECOVERED",
            requires_clock_advance=False,
        )

    # -- builders ----------------------------------------------------------

    def _customer(
        self,
        *,
        key: str,
        name: str,
        total: int,
        failed: int,
        success_rate: float,
        subscription: SubscriptionStatus,
        average: int,
    ) -> Customer:
        now = self._clock.now()
        customer = Customer(
            customer_id=f"cust_demo_{key}",
            historical_payment_count=total,
            successful_payment_count=total - failed,
            failed_payment_count=failed,
            historical_success_rate=success_rate,
            average_transaction_value=average,
            subscription_status=subscription,
            meta={"source": SYNTHETIC_MARKER, "scenario": key.upper()},
            is_synthetic=True,
            name=name,
            created_at=now - timedelta(days=180),
            updated_at=now,
        )
        self._session.merge(customer)
        self._session.flush()
        return self._session.get(Customer, customer.customer_id)

    def _at_risk_payment(
        self,
        *,
        key: str,
        customer: Customer,
        amount: int,
        method: PaymentMethod,
        reason: FailureReason,
        attempts: int,
    ) -> tuple[Payment, RecoveryCase]:
        """Create a failed payment with its attempt history, and open its case."""
        now = self._clock.now()

        payment = Payment(
            payment_id=f"pay_demo_{key}",
            customer_id=customer.customer_id,
            amount=amount,
            currency=self._settings.default_currency,
            payment_method=method,
            status=PaymentStatus.FAILED,
            attempt_count=attempts,
            failure_reason=reason,
            merchant_id="merch_demo",
            meta={"source": SYNTHETIC_MARKER, "scenario": key.upper()},
            is_synthetic=True,
            created_at=now,
            updated_at=now,
        )
        self._session.merge(payment)
        self._session.flush()
        payment = self._session.get(Payment, payment.payment_id)

        # One recorded failed attempt per prior try, so the history is coherent
        # with attempt_count rather than merely asserted by it.
        for number in range(1, attempts + 1):
            attempt = PaymentAttempt(
                attempt_id=f"att_demo_{key}_{number}",
                payment_id=payment.payment_id,
                attempt_number=number,
                status=PaymentStatus.FAILED,
                failure_reason=reason,
                action_type=None,
                provider_response={"simulated": True, "origin": SYNTHETIC_MARKER},
                source=(
                    "subscription_charge"
                    if reason is FailureReason.SUBSCRIPTION_FAILURE
                    else "checkout"
                ),
                attempted_at=now,
            )
            self._session.merge(attempt)
        self._session.flush()

        case = self._detector.detect_and_open_case(payment, case_id=f"case_demo_{key}")
        self._session.flush()
        return payment, case

    def _background_customers(self, count: int) -> list[Customer]:
        """A spread of reliable and unreliable customers."""
        first = ("Aarav", "Diya", "Kabir", "Meera", "Rohan", "Sana", "Arjun", "Neha")
        last = ("Kapoor", "Nair", "Rao", "Singh", "Bose", "Menon", "Joshi", "Verma")

        customers: list[Customer] = []
        now = self._clock.now()

        for index in range(count):
            total = 4 + (index * 3) % 26
            failed = index % 5
            subscription = (
                SubscriptionStatus.ACTIVE
                if index % 3 == 0
                else SubscriptionStatus.PAST_DUE
                if index % 7 == 0
                else SubscriptionStatus.NONE
            )
            customer = Customer(
                customer_id=f"cust_seed_{index:04d}",
                historical_payment_count=total,
                successful_payment_count=max(total - failed, 0),
                failed_payment_count=failed,
                historical_success_rate=round(max(total - failed, 0) / total, 3) if total else 0.0,
                average_transaction_value=120_000 + index * 35_000,
                subscription_status=subscription,
                meta={"source": SYNTHETIC_MARKER},
                is_synthetic=True,
                name=f"{first[index % len(first)]} {last[index % len(last)]}",
                created_at=now - timedelta(days=240 - index * 5),
                updated_at=now,
            )
            self._session.merge(customer)
            customers.append(customer)

        self._session.flush()
        return customers

    def _background_payments(self, customers: list[Customer]) -> list[Payment]:
        """One at-risk payment per background customer, cycling the failure reasons.

        Cases are opened for these too, so ``GET /recovery/cases`` and the analytics
        endpoints have a realistic population immediately after seeding.
        """
        payments: list[Payment] = []
        now = self._clock.now()

        for index, customer in enumerate(customers):
            reason, method, amount = _BACKGROUND_MIX[index % len(_BACKGROUND_MIX)]
            status = (
                PaymentStatus.ABANDONED
                if reason is FailureReason.CHECKOUT_ABANDONMENT
                else PaymentStatus.FAILED
            )

            payment = Payment(
                payment_id=f"pay_seed_{index:04d}",
                customer_id=customer.customer_id,
                amount=amount + index * 5_000,
                currency=self._settings.default_currency,
                payment_method=method,
                status=status,
                attempt_count=1,
                failure_reason=reason,
                merchant_id="merch_demo",
                meta={"source": SYNTHETIC_MARKER},
                is_synthetic=True,
                created_at=now - timedelta(hours=self._rng.randint(1, 20)),
                updated_at=now,
            )
            self._session.merge(payment)
            self._session.flush()
            payment = self._session.get(Payment, payment.payment_id)

            attempt = PaymentAttempt(
                attempt_id=f"att_seed_{index:04d}_1",
                payment_id=payment.payment_id,
                attempt_number=1,
                status=status,
                failure_reason=reason,
                action_type=None,
                provider_response={"simulated": True, "origin": SYNTHETIC_MARKER},
                source=(
                    "subscription_charge"
                    if reason is FailureReason.SUBSCRIPTION_FAILURE
                    else "checkout"
                ),
                attempted_at=payment.created_at,
            )
            self._session.merge(attempt)
            self._session.flush()

            self._detector.detect_and_open_case(payment, case_id=f"case_seed_{index:04d}")
            payments.append(payment)

        self._session.flush()
        return payments


__all__ = ["SYNTHETIC_MARKER", "DemoScenario", "ScenarioGenerator", "SeedSummary"]
