"""Schema tests (Requirement 24.6, 24.7)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.enums import FailureReason, PaymentStatus
from app.schemas.analytics import ActionCounts, RevenueAnalyticsResponse
from app.schemas.common import SYNTHETIC_DATA_SOURCE, ErrorResponse, Money, Page
from app.schemas.payment import PaymentDetail, PaymentRead, SimulatePaymentRequest
from app.schemas.simulate import AdvanceClockRequest

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "app" / "schemas"


def test_money_is_an_integer_with_a_currency_code():
    """Requirement 24.7."""
    money = Money.of(1_000_000)
    assert money.amount == 1_000_000
    assert isinstance(money.amount, int)
    assert money.currency == "INR"


def test_money_rejects_a_non_numeric_amount():
    with pytest.raises(ValidationError):
        Money(amount="lots", currency="INR")


def test_error_envelope_shape():
    """Requirement 1.8."""
    payload = ErrorResponse(error={"code": "NOT_FOUND", "message": "missing"}).model_dump()
    assert payload == {"error": {"code": "NOT_FOUND", "message": "missing"}}


def test_simulate_payment_request_requires_a_positive_amount():
    with pytest.raises(ValidationError):
        SimulatePaymentRequest(amount=0)


def test_simulate_payment_request_defaults():
    request = SimulatePaymentRequest(amount=500_000)
    assert request.currency == "INR"
    assert request.status == PaymentStatus.CREATED
    assert request.failure_reason is None


def test_advance_clock_requires_non_zero_movement():
    with pytest.raises(ValidationError, match="non-zero"):
        AdvanceClockRequest()
    assert AdvanceClockRequest(minutes=15).minutes == 15


def test_advance_clock_rejects_negative_values():
    with pytest.raises(ValidationError):
        AdvanceClockRequest(minutes=-1)


def test_payment_read_maps_amount_into_money(payment_factory):
    payment = payment_factory(amount=1_000_000, status=PaymentStatus.FAILED,
                              failure_reason=FailureReason.BANK_TIMEOUT)
    read = PaymentRead.from_model(payment)
    assert read.money.amount == 1_000_000
    assert read.money.currency == "INR"
    assert read.failure_reason is FailureReason.BANK_TIMEOUT
    # No bare float amount leaks into the payload.
    assert "amount" not in read.model_dump()


def test_payment_detail_includes_attempt_history(db, payment_factory, clock):
    from app.models import PaymentAttempt

    payment = payment_factory(status=PaymentStatus.FAILED)
    db.add(
        PaymentAttempt(
            attempt_id="att_schema_1",
            payment_id=payment.payment_id,
            attempt_number=1,
            status=PaymentStatus.FAILED,
            failure_reason=FailureReason.BANK_TIMEOUT,
            provider_response={"simulated": True},
            source="checkout",
            attempted_at=clock.now(),
        )
    )
    db.commit()
    db.refresh(payment)

    detail = PaymentDetail.from_model(payment)
    assert len(detail.attempts) == 1
    assert detail.attempts[0].attempt_id == "att_schema_1"


def test_analytics_payload_is_labelled_synthetic():
    """Requirement 20.5, 27.1."""
    payload = RevenueAnalyticsResponse(
        revenue_at_risk=Money.of(0),
        revenue_recovered=Money.of(0),
        recovery_rate=0.0,
        average_recovery_value=Money.of(0),
        cases_total=0,
        cases_recovered=0,
        payments_at_risk=0,
    ).model_dump()

    assert payload["data_source"] == SYNTHETIC_DATA_SOURCE
    assert "synthetic" in payload["notice"].lower()
    assert "no real money" in payload["notice"].lower()


def test_page_envelope():
    page = Page[int](items=[1, 2], total=2, limit=50, offset=0)
    assert page.items == [1, 2]
    assert page.total == 2


def test_action_counts_fields():
    counts = ActionCounts(selected=1, successful=1, failed=0, stopped=0, escalated=0)
    assert set(counts.model_dump()) == {
        "selected",
        "successful",
        "failed",
        "stopped",
        "escalated",
    }


def test_schemas_do_not_import_sqlalchemy():
    """Schemas describe the wire format, not the database."""
    offenders: list[str] = []
    for path in sorted(SCHEMAS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module.split(".")[0]}
            else:
                continue
            if "sqlalchemy" in names:
                offenders.append(path.name)
    assert offenders == []
