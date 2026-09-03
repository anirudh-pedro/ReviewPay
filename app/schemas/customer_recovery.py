"""Customer-facing recovery schemas for RevivePay."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ActionType, FailureReason
from app.schemas.common import Money


class CustomerRecoveryViewResponse(BaseModel):
    """Customer-facing recovery portal information."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str
    payment_id: str
    order_id: str | None = None
    merchant_name: str = "Demo Merchant Store"
    amount: Money
    status: str = Field(description="PENDING_RECOVERY, RECOVERED, or EXPIRED")

    # Friendly diagnosis
    failure_reason: FailureReason
    failure_title: str
    failure_explanation: str

    # Recovery solution chosen by RevivePay
    recommended_action: ActionType
    solution_title: str
    solution_description: str
    action_type: str = Field(description="UPI_QR, ALTERNATIVE_PAYMENT, or SMART_RETRY")

    # Available recovery instruments
    available_methods: list[str] = Field(default_factory=lambda: ["UPI", "Card", "Netbanking"])
    simulated_upi_qr: str = Field(description="Simulated UPI payment payload")
    cooldown_seconds: int = 0
    expires_at: str | None = None


class CustomerRecoveryExecutionRequest(BaseModel):
    """Customer submission to complete payment recovery."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    selected_method: str = Field(default="UPI", description="Payment method used for recovery: UPI, CARD, or NETBANKING")
    instrument_details: dict[str, Any] = Field(default_factory=dict, description="Optional instrument details")


class CustomerRecoveryExecutionResponse(BaseModel):
    """Result of customer recovery execution."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    success: bool
    receipt_id: str
    case_id: str
    payment_id: str
    amount_recovered: Money
    recovered_at: str
    message: str


class SendRecoveryEmailRequest(BaseModel):
    """Request to send a real recovery email to a customer."""

    recipient_email: str = Field(description="Target customer email address")
    customer_name: str = Field(default="Valued Customer")
    portal_base_url: str | None = Field(default=None, description="Base frontend URL, e.g. http://localhost:5173")


class SendRecoveryEmailResponse(BaseModel):
    """Result of dispatching recovery email."""

    success: bool
    provider: str
    recipient: str
    message: str
    message_id: str | None = None
    mailto_fallback_url: str | None = None
    error: str | None = None


class VoiceRecoveryRequest(BaseModel):
    """Request to initiate an automated Exotel outbound voice recovery call."""

    customer_phone: str = Field(min_length=6, max_length=25, description="Destination phone number")
    customer_name: str = Field(default="Valued Customer", max_length=100)
    portal_base_url: str = Field(default="http://localhost:5173", description="Base frontend URL")


class VoiceRecoveryResponse(BaseModel):
    """Result of initiating voice recovery call."""

    case_id: str
    channel: str = "VOICE"
    status: str
    call_id: str | None = None
    payment_link: str
    policy_decision: str
    message: str
    success: bool
    error: str | None = None


class VoiceStatusWebhookResponse(BaseModel):
    """Response returned from Exotel status webhook callback."""

    received: bool
    case_id: str | None = None
    call_id: str | None = None
    status: str | None = None
