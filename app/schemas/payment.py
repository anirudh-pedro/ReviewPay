"""Payment request and response schemas (Requirement 24.2, 24.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ActionType, FailureReason, PaymentMethod, PaymentStatus
from app.schemas.common import Money


class SimulatePaymentRequest(BaseModel):
    """Create a synthetic payment.

    Omitting ``customer_id`` generates a synthetic customer with a plausible
    history, which is the fastest path to a demonstrable at-risk payment.
    """

    customer_id: str | None = Field(default=None, examples=["cust_0001"])
    amount: int = Field(gt=0, description="Amount in minor units (paise).", examples=[1_000_000])
    currency: str = Field(default="INR", examples=["INR"])
    payment_method: PaymentMethod = Field(default=PaymentMethod.UPI)
    status: PaymentStatus = Field(
        default=PaymentStatus.CREATED,
        description="Initial status. Use FAILED together with failure_reason to create an at-risk payment directly.",
    )
    failure_reason: FailureReason | None = Field(default=None)
    merchant_id: str = Field(default="merch_demo")
    metadata: dict[str, Any] = Field(default_factory=dict)


class FailPaymentRequest(BaseModel):
    """Fail an existing payment with a specific cause."""

    failure_reason: FailureReason = Field(examples=[FailureReason.BANK_TIMEOUT])


class PaymentAttemptRead(BaseModel):
    """One charge attempt."""

    model_config = ConfigDict(from_attributes=True)

    attempt_id: str
    attempt_number: int
    status: PaymentStatus
    failure_reason: FailureReason | None = None
    action_type: ActionType | None = Field(
        default=None, description="Set when the attempt came from a recovery action."
    )
    source: str
    provider_response: dict[str, Any] = Field(default_factory=dict)
    attempted_at: datetime


class PaymentRead(BaseModel):
    """A payment as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    payment_id: str
    customer_id: str
    money: Money
    payment_method: PaymentMethod
    status: PaymentStatus
    attempt_count: int
    failure_reason: FailureReason | None = None
    merchant_id: str
    is_synthetic: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, payment) -> "PaymentRead":
        return cls(
            payment_id=payment.payment_id,
            customer_id=payment.customer_id,
            money=Money.of(payment.amount, payment.currency),
            payment_method=payment.payment_method,
            status=payment.status,
            attempt_count=payment.attempt_count,
            failure_reason=payment.failure_reason,
            merchant_id=payment.merchant_id,
            is_synthetic=payment.is_synthetic,
            created_at=payment.created_at,
            updated_at=payment.updated_at,
        )


class PaymentDetail(PaymentRead):
    """A payment with its full attempt history (Requirement 4.5)."""

    attempts: list[PaymentAttemptRead] = Field(default_factory=list)

    @classmethod
    def from_model(cls, payment) -> "PaymentDetail":
        base = PaymentRead.from_model(payment)
        return cls(
            **base.model_dump(),
            attempts=[PaymentAttemptRead.model_validate(item) for item in payment.attempts],
        )


class FailPaymentResponse(BaseModel):
    """The failed payment plus the recovery case opened for it."""

    payment: PaymentRead
    case_id: str | None = Field(
        default=None, description="Recovery case opened or reused for this payment."
    )
    case_state: str | None = None
    amount_at_risk: Money | None = None
