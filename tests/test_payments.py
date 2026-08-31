"""Payment service and endpoint tests (Requirement 4.1-4.6, 24.2, 24.8)."""

from __future__ import annotations

import pytest

from app.core.enums import FailureReason, PaymentMethod, PaymentStatus
from app.core.errors import RecordNotFound
from app.services.payment_service import (
    SOURCE_CHECKOUT,
    SOURCE_RECOVERY,
    SOURCE_SUBSCRIPTION,
    PaymentService,
)


@pytest.fixture
def service(db, clock) -> PaymentService:
    return PaymentService(db, clock)


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


def test_create_payment_persists_minor_units(service, clock):
    """Requirement 4.1, 2.8."""
    payment = service.create_payment(amount=1_000_000, payment_method=PaymentMethod.UPI)

    assert payment.amount == 1_000_000
    assert isinstance(payment.amount, int)
    assert payment.currency == "INR"
    assert payment.status is PaymentStatus.CREATED
    assert payment.attempt_count == 0
    assert payment.created_at == clock.now()


def test_create_payment_generates_a_synthetic_customer(service):
    payment = service.create_payment(amount=100_000)
    assert payment.customer_id.startswith("cust_")
    assert payment.customer.is_synthetic is True
    assert payment.customer.historical_success_rate == pytest.approx(0.94)


def test_create_payment_reuses_a_named_customer(service, customer_factory):
    customer = customer_factory(customer_id="cust_named_0001")
    payment = service.create_payment(amount=100_000, customer_id="cust_named_0001")
    assert payment.customer_id == customer.customer_id


def test_create_failed_payment_records_an_attempt(service):
    """A payment created as FAILED is immediately a valid detection input."""
    payment = service.create_payment(
        amount=500_000,
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.BANK_TIMEOUT,
    )

    assert payment.status is PaymentStatus.FAILED
    assert payment.failure_reason is FailureReason.BANK_TIMEOUT
    assert payment.attempt_count == 1
    assert len(payment.attempts) == 1
    assert payment.attempts[0].attempt_number == 1
    assert payment.attempts[0].status is PaymentStatus.FAILED


def test_failure_reason_is_ignored_for_a_successful_status(service):
    payment = service.create_payment(
        amount=500_000,
        status=PaymentStatus.SUCCEEDED,
        failure_reason=FailureReason.BANK_TIMEOUT,
    )
    assert payment.failure_reason is None


def test_every_created_record_is_flagged_synthetic(service):
    """Requirement 4.6."""
    payment = service.create_payment(amount=100_000)
    assert payment.is_synthetic is True
    assert payment.customer.is_synthetic is True


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------


def test_fail_payment_updates_status_reason_and_attempt_count(service, payment_factory):
    """Requirement 4.2."""
    payment = payment_factory(status=PaymentStatus.CREATED, attempt_count=0)

    failed = service.fail_payment(payment.payment_id, FailureReason.INSUFFICIENT_FUNDS)

    assert failed.status is PaymentStatus.FAILED
    assert failed.failure_reason is FailureReason.INSUFFICIENT_FUNDS
    assert failed.attempt_count == 1
    assert len(failed.attempts) == 1
    assert failed.attempts[0].failure_reason is FailureReason.INSUFFICIENT_FUNDS


def test_repeated_failures_accumulate_attempts(service, payment_factory):
    payment = payment_factory(attempt_count=0)

    service.fail_payment(payment.payment_id, FailureReason.BANK_TIMEOUT)
    service.fail_payment(payment.payment_id, FailureReason.BANK_TIMEOUT)

    refreshed = service.get_payment_with_attempts(payment.payment_id)
    assert refreshed.attempt_count == 2
    assert [item.attempt_number for item in refreshed.attempts] == [1, 2]


def test_fail_payment_raises_for_an_unknown_payment(service):
    """Requirement 4.4."""
    with pytest.raises(RecordNotFound):
        service.fail_payment("pay_missing", FailureReason.BANK_TIMEOUT)


@pytest.mark.parametrize(
    ("reason", "expected_source"),
    [
        (FailureReason.BANK_TIMEOUT, SOURCE_CHECKOUT),
        (FailureReason.CHECKOUT_ABANDONMENT, SOURCE_CHECKOUT),
        (FailureReason.SUBSCRIPTION_FAILURE, SOURCE_SUBSCRIPTION),
    ],
)
def test_attempt_provenance_is_recorded(service, payment_factory, reason, expected_source):
    """Requirement 4.3, 4.4: provenance lives on the attempt, not a separate table."""
    payment = payment_factory(attempt_count=0)
    service.fail_payment(payment.payment_id, reason)

    refreshed = service.get_payment_with_attempts(payment.payment_id)
    assert refreshed.attempts[-1].source == expected_source


def test_abandonment_and_subscription_failure_use_the_payment_record(service, payment_factory):
    """Requirement 4.3: no separate entity for either channel."""
    for reason in (FailureReason.CHECKOUT_ABANDONMENT, FailureReason.SUBSCRIPTION_FAILURE):
        payment = payment_factory(attempt_count=0)
        failed = service.fail_payment(payment.payment_id, reason)
        assert failed.failure_reason is reason
        assert failed.status is PaymentStatus.FAILED


# ---------------------------------------------------------------------------
# Recovery attempts
# ---------------------------------------------------------------------------


def test_record_recovery_attempt_marks_the_action(service, payment_factory):
    from app.core.enums import ActionType

    payment = payment_factory(
        status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT, attempt_count=1
    )

    service.record_recovery_attempt(
        payment=payment,
        status=PaymentStatus.SUCCEEDED,
        action=ActionType.RETRY_LATER,
        provider_response={"simulated": True},
    )

    refreshed = service.get_payment_with_attempts(payment.payment_id)
    assert refreshed.status is PaymentStatus.SUCCEEDED
    assert refreshed.failure_reason is None
    assert refreshed.attempt_count == 2
    assert refreshed.attempts[-1].action_type is ActionType.RETRY_LATER
    assert refreshed.attempts[-1].source == SOURCE_RECOVERY


def test_failed_recovery_attempt_preserves_the_failure_reason(service, payment_factory):
    from app.core.enums import ActionType

    payment = payment_factory(
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS,
        attempt_count=1,
    )

    service.record_recovery_attempt(
        payment=payment,
        status=PaymentStatus.FAILED,
        action=ActionType.RETRY_LATER,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS,
    )

    refreshed = service.get_payment_with_attempts(payment.payment_id)
    assert refreshed.status is PaymentStatus.FAILED
    assert refreshed.failure_reason is FailureReason.INSUFFICIENT_FUNDS
    assert refreshed.attempt_count == 2


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def test_list_payments_is_paginated(service):
    for index in range(5):
        service.create_payment(amount=100_000 + index)

    page = service.list_payments(limit=2, offset=0)
    assert len(page.items) == 2
    assert page.total == 5
    assert page.limit == 2


def test_list_payments_filters_by_status(service):
    service.create_payment(amount=100_000, status=PaymentStatus.SUCCEEDED)
    service.create_payment(
        amount=200_000, status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT
    )

    failed = service.list_payments(status=PaymentStatus.FAILED)
    assert failed.total == 1
    assert failed.items[0].status is PaymentStatus.FAILED


def test_list_at_risk_payments_covers_failed_and_abandoned(service):
    service.create_payment(amount=100_000, status=PaymentStatus.SUCCEEDED)
    service.create_payment(
        amount=200_000, status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT
    )
    service.create_payment(
        amount=300_000,
        status=PaymentStatus.ABANDONED,
        failure_reason=FailureReason.CHECKOUT_ABANDONMENT,
    )

    at_risk = service.list_at_risk_payments()
    assert len(at_risk) == 2
    assert {item.status for item in at_risk} == {PaymentStatus.FAILED, PaymentStatus.ABANDONED}


def test_get_payment_raises_for_an_unknown_id(service):
    with pytest.raises(RecordNotFound):
        service.get_payment("pay_missing")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def test_simulate_endpoint_creates_a_payment(api_client, api_prefix):
    """Requirement 24.2."""
    response = api_client.post(
        f"{api_prefix}/payments/simulate",
        json={"amount": 1_000_000, "payment_method": "UPI"},
    )
    assert response.status_code == 201

    body = response.json()
    assert body["money"] == {"amount": 1_000_000, "currency": "INR"}
    assert body["status"] == "CREATED"
    assert body["is_synthetic"] is True


def test_simulate_endpoint_rejects_a_non_positive_amount(api_client, api_prefix):
    response = api_client.post(f"{api_prefix}/payments/simulate", json={"amount": 0})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "amount" in response.json()["error"]["message"]


def test_fail_endpoint_opens_a_recovery_case(api_client, api_prefix):
    """Requirement 4.2, 5.2."""
    created = api_client.post(
        f"{api_prefix}/payments/simulate", json={"amount": 1_000_000}
    ).json()

    response = api_client.post(
        f"{api_prefix}/payments/{created['payment_id']}/fail",
        json={"failure_reason": "BANK_TIMEOUT"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["payment"]["status"] == "FAILED"
    assert body["payment"]["failure_reason"] == "BANK_TIMEOUT"
    assert body["payment"]["attempt_count"] == 1
    assert body["case_id"].startswith("case_")
    assert body["case_state"] == "DETECTED"
    assert body["amount_at_risk"] == {"amount": 1_000_000, "currency": "INR"}


def test_fail_endpoint_returns_404_for_an_unknown_payment(api_client, api_prefix):
    """Requirement 24.8."""
    response = api_client.post(
        f"{api_prefix}/payments/pay_missing/fail",
        json={"failure_reason": "BANK_TIMEOUT"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_fail_endpoint_rejects_an_invalid_failure_reason(api_client, api_prefix):
    """Requirement 3.6."""
    created = api_client.post(f"{api_prefix}/payments/simulate", json={"amount": 100_000}).json()

    response = api_client.post(
        f"{api_prefix}/payments/{created['payment_id']}/fail",
        json={"failure_reason": "NETWORK_FAILURE"},  # renamed to NETWORK_ERROR
    )
    assert response.status_code == 422
    assert "failure_reason" in response.json()["error"]["message"]


def test_get_payment_endpoint_includes_attempts(api_client, api_prefix):
    """Requirement 4.5."""
    created = api_client.post(f"{api_prefix}/payments/simulate", json={"amount": 100_000}).json()
    api_client.post(
        f"{api_prefix}/payments/{created['payment_id']}/fail",
        json={"failure_reason": "EXPIRED_CARD"},
    )

    response = api_client.get(f"{api_prefix}/payments/{created['payment_id']}")
    assert response.status_code == 200

    body = response.json()
    assert len(body["attempts"]) == 1
    assert body["attempts"][0]["failure_reason"] == "EXPIRED_CARD"


def test_get_payment_endpoint_returns_404(api_client, api_prefix):
    response = api_client.get(f"{api_prefix}/payments/pay_missing")
    assert response.status_code == 404


def test_list_payments_endpoint_paginates(api_client, api_prefix):
    for _ in range(3):
        api_client.post(f"{api_prefix}/payments/simulate", json={"amount": 100_000})

    response = api_client.get(f"{api_prefix}/payments", params={"limit": 2, "offset": 0})
    assert response.status_code == 200

    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert body["limit"] == 2


def test_list_payments_endpoint_filters_by_status(api_client, api_prefix):
    created = api_client.post(f"{api_prefix}/payments/simulate", json={"amount": 100_000}).json()
    api_client.post(
        f"{api_prefix}/payments/{created['payment_id']}/fail",
        json={"failure_reason": "BANK_TIMEOUT"},
    )

    response = api_client.get(f"{api_prefix}/payments", params={"status": "FAILED"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
