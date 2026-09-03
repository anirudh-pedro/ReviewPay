"""Tests for the end-to-end Razorpay payment failure and Customer Recovery portal flow."""

from __future__ import annotations

import pytest

from app.api.deps import razorpay_client_dep, settings_dep
from app.core.config import Settings
from app.core.enums import FailureReason
from tests.test_razorpay_gateway import FakeRazorpay, _create_order, _gateway_settings


@pytest.fixture
def gateway_setup(api_client, settings, api_prefix):
    fake = FakeRazorpay()
    api_client.app.dependency_overrides[settings_dep] = lambda: _gateway_settings(settings)
    api_client.app.dependency_overrides[razorpay_client_dep] = lambda: fake
    return api_client, fake, api_prefix


def test_simulate_order_failure_and_revivepay_takeover(gateway_setup):
    client, _, prefix = gateway_setup
    order = _create_order(client, prefix)
    order_id = order["order_id"]

    # 1. Simulate payment failure on real Sandbox order with EXPIRED_CARD
    # In Scripted Outcomes, EXPIRED_CARD fails on RETRY_NOW and requires customer action (CHANGE_PAYMENT_METHOD)
    response = client.post(
        f"{prefix}/gateway/razorpay/orders/{order_id}/simulate-failure",
        json={
            "failure_reason": FailureReason.EXPIRED_CARD.value,
            "error_description": "Card expired or blocked by issuer",
            "payment_method": "card",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["recovery_case_id"] is not None
    assert data["failure_reason"] == FailureReason.EXPIRED_CARD.value
    assert data["customer_recovery_url"].startswith("/recover/")

    case_id = data["recovery_case_id"]

    # 2. Query customer recovery view
    cust_resp = client.get(f"{prefix}/recovery/cases/{case_id}/customer-view")
    assert cust_resp.status_code == 200
    cust_data = cust_resp.json()
    assert cust_data["case_id"] == case_id
    assert "Card" in cust_data["failure_title"] or "Declined" in cust_data["failure_title"]
    assert "UPI" in cust_data["available_methods"]
    assert cust_data["simulated_upi_qr"].startswith("upi://pay?")

    # 3. Customer completes recovery payment via alternative payment method (UPI)
    rec_resp = client.post(
        f"{prefix}/recovery/cases/{case_id}/customer-recover",
        json={"selected_method": "UPI", "instrument_details": {"vpa": "user@okaxis"}},
    )
    assert rec_resp.status_code == 200
    rec_data = rec_resp.json()
    assert rec_data["success"] is True
    assert rec_data["amount_recovered"]["amount"] == 125_00
    assert rec_data["receipt_id"].startswith("rcpt_revive_")

    # 4. Confirm customer recovery view is now RECOVERED
    cust_resp2 = client.get(f"{prefix}/recovery/cases/{case_id}/customer-view")
    assert cust_resp2.status_code == 200
    assert cust_resp2.json()["status"] == "RECOVERED"
