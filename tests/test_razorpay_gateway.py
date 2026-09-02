"""Mocked Razorpay Sandbox gateway integration and security contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest
from sqlalchemy import func, select

from app.api.deps import razorpay_client_dep, settings_dep
from app.core.config import Settings
from app.core.enums import FailureReason, PaymentStatus
from app.integrations.razorpay_failure_mapper import normalize_razorpay_failure
from app.models import GatewayPayment, GatewayWebhookEvent, Payment, PaymentAttempt, RecoveryCase


class FakeRazorpay:
    """Injectable provider fake; no test performs an external HTTP request."""

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.payments: dict[str, dict[str, Any]] = {}
        self.create_calls = 0

    def create_order(self, *, amount: int, currency: str, receipt: str, notes: dict[str, str]) -> dict[str, Any]:
        self.create_calls += 1
        order = {"id": f"order_test_{self.create_calls}", "amount": amount, "currency": currency, "status": "created"}
        self.orders[order["id"]] = order
        return order

    def fetch_order(self, provider_order_id: str) -> dict[str, Any]:
        return dict(self.orders[provider_order_id])

    def fetch_payment(self, provider_payment_id: str) -> dict[str, Any]:
        return dict(self.payments[provider_payment_id])


def _gateway_settings(settings: Settings) -> Settings:
    return Settings(
        _env_file=None,
        **{
            **settings.model_dump(),
            "razorpay_enabled": True,
            "razorpay_key_id": "rzp_test_fake",
            "razorpay_key_secret": "sandbox-key-secret",
            "razorpay_webhook_secret": "sandbox-webhook-secret",
        },
    )


@pytest.fixture
def gateway(api_client, settings, api_prefix):
    fake = FakeRazorpay()
    api_client.app.dependency_overrides[settings_dep] = lambda: _gateway_settings(settings)
    api_client.app.dependency_overrides[razorpay_client_dep] = lambda: fake
    return api_client, fake, api_prefix


def _create_order(client, prefix: str, *, key: str = "gateway-order-key-0001") -> dict[str, Any]:
    response = client.post(
        f"{prefix}/gateway/razorpay/orders",
        headers={"Idempotency-Key": key},
        json={"amount": 125_00, "currency": "INR"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _checkout_signature(order_id: str, payment_id: str) -> str:
    return hmac.new(
        b"sandbox-key-secret", f"{order_id}|{payment_id}".encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _webhook_body(*, event: str, order_id: str, payment: dict[str, Any]) -> bytes:
    return json.dumps(
        {"event": event, "payload": {"payment": {"entity": {"order_id": order_id, **payment}}}},
        separators=(",", ":"),
    ).encode("utf-8")


def _webhook_signature(body: bytes) -> str:
    return hmac.new(b"sandbox-webhook-secret", body, hashlib.sha256).hexdigest()


def test_order_creation_is_idempotent_and_creates_a_non_synthetic_payment(gateway, db):
    client, fake, prefix = gateway
    first = _create_order(client, prefix, key="gateway-order-key-idempotent")
    second = _create_order(client, prefix, key="gateway-order-key-idempotent")

    assert second["order_id"] == first["order_id"]
    assert second["payment"]["payment_id"] == first["payment"]["payment_id"]
    assert first["data_source"] == "razorpay_sandbox"
    assert fake.create_calls == 1
    payment = db.get(Payment, first["payment"]["payment_id"])
    assert payment is not None and payment.is_synthetic is False
    assert db.scalar(select(func.count()).select_from(GatewayPayment)) == 1


def test_verified_checkout_captured_payment_persists_one_safe_attempt(gateway, db):
    client, fake, prefix = gateway
    order = _create_order(client, prefix)
    payment_id = "pay_gateway_captured"
    fake.payments[payment_id] = {
        "id": payment_id,
        "order_id": order["order_id"],
        "amount": 125_00,
        "currency": "INR",
        "status": "captured",
        "method": "card",
        "email": "must-not-persist@example.test",
        "card": {"last4": "1111"},
    }

    response = client.post(
        f"{prefix}/gateway/razorpay/verify",
        json={
            "razorpay_order_id": order["order_id"],
            "razorpay_payment_id": payment_id,
            "razorpay_signature": _checkout_signature(order["order_id"], payment_id),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["payment"]["status"] == "SUCCEEDED"
    assert body["payment"]["is_synthetic"] is False
    attempts = db.scalars(select(PaymentAttempt)).all()
    assert len(attempts) == 1
    assert attempts[0].provider_response == {
        "provider": "razorpay",
        "order_id": order["order_id"],
        "payment_id": payment_id,
        "status": "captured",
        "normalized_failure_reason": None,
        "error_code": None,
        "event_type": "checkout.callback",
    }
    assert "email" not in json.dumps(attempts[0].provider_response)
    assert "last4" not in json.dumps(attempts[0].provider_response)


def test_verified_failed_webhook_normalizes_and_opens_one_recovery_case(gateway, db):
    client, fake, prefix = gateway
    order = _create_order(client, prefix)
    payment_id = "pay_gateway_failed"
    fake.payments[payment_id] = {
        "id": payment_id,
        "order_id": order["order_id"],
        "amount": 125_00,
        "currency": "INR",
        "status": "failed",
        "method": "upi",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Insufficient funds in account",
    }
    body = _webhook_body(event="payment.failed", order_id=order["order_id"], payment=fake.payments[payment_id])

    response = client.post(
        f"{prefix}/gateway/razorpay/webhooks",
        content=body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": _webhook_signature(body)},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["known_payment"] is True
    assert result["recovery_case_id"].startswith("case_")
    payment = db.get(Payment, order["payment"]["payment_id"])
    assert payment.status is PaymentStatus.FAILED
    assert payment.failure_reason is FailureReason.INSUFFICIENT_FUNDS
    assert payment.attempt_count == 1
    assert db.scalar(select(func.count()).select_from(RecoveryCase)) == 1


def test_invalid_webhook_signature_persists_nothing(gateway, db):
    client, _, prefix = gateway
    body = _webhook_body(
        event="payment.failed",
        order_id="order_unknown",
        payment={"id": "pay_unknown", "amount": 125_00, "currency": "INR", "status": "failed"},
    )
    response = client.post(
        f"{prefix}/gateway/razorpay/webhooks",
        content=body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": "incorrect"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "GATEWAY_SIGNATURE_INVALID"
    assert db.scalar(select(func.count()).select_from(GatewayWebhookEvent)) == 0
    assert db.scalar(select(func.count()).select_from(PaymentAttempt)) == 0


def test_duplicate_signed_webhook_is_idempotent(gateway, db):
    client, fake, prefix = gateway
    order = _create_order(client, prefix)
    payment_id = "pay_gateway_duplicate"
    fake.payments[payment_id] = {
        "id": payment_id,
        "order_id": order["order_id"],
        "amount": 125_00,
        "currency": "INR",
        "status": "failed",
        "method": "upi",
        "error_description": "Bank timeout",
    }
    body = _webhook_body(event="payment.failed", order_id=order["order_id"], payment=fake.payments[payment_id])
    headers = {"Content-Type": "application/json", "X-Razorpay-Signature": _webhook_signature(body)}

    first = client.post(f"{prefix}/gateway/razorpay/webhooks", content=body, headers=headers)
    second = client.post(f"{prefix}/gateway/razorpay/webhooks", content=body, headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert db.scalar(select(func.count()).select_from(GatewayWebhookEvent)) == 1
    assert db.scalar(select(func.count()).select_from(PaymentAttempt)) == 1
    assert db.scalar(select(func.count()).select_from(RecoveryCase)) == 1


def test_unknown_order_is_a_safe_not_found_verification_error(gateway):
    client, _, prefix = gateway
    response = client.post(
        f"{prefix}/gateway/razorpay/verify",
        json={
            "razorpay_order_id": "order_missing",
            "razorpay_payment_id": "pay_missing",
            "razorpay_signature": _checkout_signature("order_missing", "pay_missing"),
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    ("payload", "event", "expected"),
    [
        ({"error_description": "Bank timed out"}, "payment.failed", FailureReason.BANK_TIMEOUT),
        ({"error_description": "Insufficient funds"}, "payment.failed", FailureReason.INSUFFICIENT_FUNDS),
        ({"error_description": "Expired card"}, "payment.failed", FailureReason.EXPIRED_CARD),
        ({"error_description": "Network connection failed"}, "payment.failed", FailureReason.NETWORK_ERROR),
        ({"error_description": "Checkout dismissed"}, "payment.failed", FailureReason.CHECKOUT_ABANDONMENT),
        ({"error_description": "Subscription recurring charge failed"}, "payment.failed", FailureReason.SUBSCRIPTION_FAILURE),
        ({"error_description": "An unfamiliar provider issue"}, "payment.failed", FailureReason.UNKNOWN),
    ],
)
def test_razorpay_failure_normalization(payload, event, expected):
    assert normalize_razorpay_failure(payload, event_type=event) is expected
