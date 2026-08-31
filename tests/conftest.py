"""Shared test fixtures.

Every test runs against a temporary SQLite database created for the test session,
a virtual clock backed by a temporary state file, and a fixed simulation seed. No
test touches the network or the developer's own ``revivepay.db``
(Requirement 25.14).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import VirtualClock
from app.core.config import Settings
from app.core.enums import PaymentMethod, PaymentStatus, SubscriptionStatus
from app.db.base import Base
from app.models import ALL_MODELS, Customer, Payment

# Fixed simulation start, chosen so the canonical RETRY_LATER timeline reads
# naturally: fail at 13:00, schedule for 13:16, advance 15 minutes.
SIM_START = datetime(2026, 1, 1, 13, 0, 0)
TEST_SEED = 20260101


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def db_path(tmp_path_factory) -> str:
    return str(tmp_path_factory.mktemp("db") / "revivepay_test.db")


@pytest.fixture(scope="session")
def db_engine(db_path):
    """The SQLAlchemy engine for the temporary test database.

    Named ``db_engine`` rather than ``engine`` so it cannot be shadowed by a test
    module's own ``engine`` fixture (the decision engine, for instance).
    """
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def session_factory(db_engine) -> sessionmaker[Session]:
    return sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory) -> Iterator[Session]:
    """A clean session. All rows are removed after each test."""
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        # Delete in reverse dependency order so foreign keys stay satisfied.
        for model in reversed(ALL_MODELS):
            session.execute(delete(model))
        session.commit()
        session.close()


# ---------------------------------------------------------------------------
# Clock and settings
# ---------------------------------------------------------------------------


@pytest.fixture
def clock(tmp_path) -> VirtualClock:
    """A virtual clock starting at the canonical demo time."""
    return VirtualClock(state_path=tmp_path / "clock.json", start=SIM_START)


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Settings with deterministic simulation values and no .env influence."""
    return Settings(
        _env_file=None,
        database_url="sqlite:///:memory:",
        simulation_seed=TEST_SEED,
        virtual_clock_start=SIM_START,
        virtual_clock_state_path=str(tmp_path / "clock.json"),
        retry_later_delay_minutes=15,
        max_automatic_retries=2,
        repeated_failure_limit=3,
        high_value_escalation_threshold=5_000_000,
        allow_human_escalation=True,
    )


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(db, session_factory, clock, settings):
    """A TestClient wired to the temporary database and the test clock.

    Overrides the session, settings, and clock dependencies so no request touches
    the developer's own database or wall-clock time.

    Depends on ``db`` so that its row cleanup runs after each test; without it,
    HTTP-created records would leak into the next test.
    """
    from fastapi.testclient import TestClient

    from app.api.deps import clock_dep, settings_dep
    from app.db.session import get_session
    from app.main import create_app

    app = create_app()

    def _session_override() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[clock_dep] = lambda: clock

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def api_prefix(settings) -> str:
    return settings.api_prefix


# ---------------------------------------------------------------------------
# Domain fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def customer_factory(db, clock):
    """Create a persisted customer with a controllable history."""

    counter = {"n": 0}

    def _make(
        *,
        success_rate: float = 0.94,
        total_payments: int = 18,
        failed_payments: int = 1,
        subscription: SubscriptionStatus = SubscriptionStatus.ACTIVE,
        average_transaction_value: int = 400_000,
        customer_id: str | None = None,
    ) -> Customer:
        counter["n"] += 1
        now = clock.now()
        customer = Customer(
            customer_id=customer_id or f"cust_test_{counter['n']:04d}",
            historical_payment_count=total_payments,
            successful_payment_count=max(total_payments - failed_payments, 0),
            failed_payment_count=failed_payments,
            historical_success_rate=success_rate,
            average_transaction_value=average_transaction_value,
            subscription_status=subscription,
            meta={"source": "test"},
            is_synthetic=True,
            name=f"Test Customer {counter['n']}",
            created_at=now,
            updated_at=now,
        )
        db.add(customer)
        db.commit()
        return customer

    return _make


@pytest.fixture
def payment_factory(db, clock, customer_factory):
    """Create a persisted payment, defaulting to a fresh synthetic customer."""

    counter = {"n": 0}

    def _make(
        *,
        amount: int = 1_000_000,
        status: PaymentStatus = PaymentStatus.CREATED,
        failure_reason=None,
        payment_method: PaymentMethod = PaymentMethod.UPI,
        attempt_count: int = 0,
        customer: Customer | None = None,
        payment_id: str | None = None,
    ) -> Payment:
        counter["n"] += 1
        owner = customer or customer_factory()
        now = clock.now()
        payment = Payment(
            payment_id=payment_id or f"pay_test_{counter['n']:04d}",
            customer_id=owner.customer_id,
            amount=amount,
            currency="INR",
            payment_method=payment_method,
            status=status,
            attempt_count=attempt_count,
            failure_reason=failure_reason,
            merchant_id="merch_test",
            meta={"source": "test"},
            is_synthetic=True,
            created_at=now,
            updated_at=now,
        )
        db.add(payment)
        db.commit()
        return payment

    return _make
