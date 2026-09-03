"""Wire contracts for the isolated Razorpay sandbox gateway."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.enums import ActionType, FailureReason
from app.schemas.common import Money
from app.schemas.payment import PaymentRead


GATEWAY_DATA_SOURCE = "razorpay_sandbox"
GATEWAY_NOTICE = (
    "Razorpay Sandbox checkout. This is separate from RevivePay's deterministic "
    "synthetic simulator; no production credentials or real-money claims are used."
)


class RazorpayOrderCreateRequest(BaseModel):
    amount: int = Field(gt=0, description="Amount in INR minor units (paise).")
    currency: Literal["INR"] = "INR"
    customer_id: str | None = Field(default=None, max_length=64)
    merchant_id: str = Field(default="merch_gateway_demo", max_length=64)


class RazorpayOrderResponse(BaseModel):
    data_source: str = GATEWAY_DATA_SOURCE
    notice: str = GATEWAY_NOTICE
    key_id: str
    order_id: str
    payment: PaymentRead
    money: Money


class RazorpayCheckoutVerificationRequest(BaseModel):
    razorpay_order_id: str = Field(min_length=1, max_length=128)
    razorpay_payment_id: str = Field(min_length=1, max_length=128)
    razorpay_signature: str = Field(min_length=1, max_length=256)


class RazorpayVerificationResponse(BaseModel):
    data_source: str = GATEWAY_DATA_SOURCE
    notice: str = GATEWAY_NOTICE
    payment: PaymentRead
    verified_provider_status: str
    recovery_case_id: str | None = None
    recovery_case_state: str | None = None


class RazorpayWebhookResponse(BaseModel):
    accepted: bool = True
    duplicate: bool
    known_payment: bool
    payment_id: str | None = None
    recovery_case_id: str | None = None


class GatewayFailureSimulationRequest(BaseModel):
    """Operator request to simulate a specific failure scenario on a Sandbox order."""

    failure_reason: FailureReason
    error_description: str | None = Field(default=None, max_length=500)
    payment_method: str = Field(default="card", max_length=32)


class GatewayFailureSimulationResponse(BaseModel):
    """Result of gateway failure and RevivePay autonomous takeover."""

    data_source: str = GATEWAY_DATA_SOURCE
    notice: str = GATEWAY_NOTICE
    payment: PaymentRead
    recovery_case_id: str
    recovery_case_state: str
    failure_reason: FailureReason
    diagnosis_explanation: str
    selected_action: ActionType | None
    policy_outcome: str
    customer_recovery_url: str


__all__ = [
    "GATEWAY_DATA_SOURCE",
    "GATEWAY_NOTICE",
    "GatewayFailureSimulationRequest",
    "GatewayFailureSimulationResponse",
    "RazorpayCheckoutVerificationRequest",
    "RazorpayOrderCreateRequest",
    "RazorpayOrderResponse",
    "RazorpayVerificationResponse",
    "RazorpayWebhookResponse",
]
