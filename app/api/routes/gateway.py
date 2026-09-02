"""Razorpay Sandbox order, verification, and signed-webhook endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request, status

from app.api.auth import OperationsPrincipalDep
from app.api.deps import ClockDep, RazorpayClientDep, SessionDep, SettingsDep
from app.schemas.common import Money
from app.schemas.gateway import (
    RazorpayCheckoutVerificationRequest,
    RazorpayOrderCreateRequest,
    RazorpayOrderResponse,
    RazorpayVerificationResponse,
    RazorpayWebhookResponse,
)
from app.schemas.payment import PaymentRead
from app.services.gateway_payment_service import GatewayPaymentService, GatewaySignatureInvalid

router = APIRouter(prefix="/gateway/razorpay", tags=["razorpay-sandbox"])


@router.post("/orders", response_model=RazorpayOrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    request: RazorpayOrderCreateRequest,
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
    client: RazorpayClientDep,
    _: OperationsPrincipalDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=255)],
) -> RazorpayOrderResponse:
    """Create/reuse a local payment and a Razorpay Sandbox order."""
    result = GatewayPaymentService(session, clock, settings, client).create_order(
        amount=request.amount,
        currency=request.currency,
        customer_id=request.customer_id,
        merchant_id=request.merchant_id,
        idempotency_key=idempotency_key,
    )
    session.commit()
    return RazorpayOrderResponse(
        key_id=settings.razorpay_key_id or "",
        order_id=result.mapping.provider_order_id,
        payment=PaymentRead.from_model(result.payment),
        money=Money.of(result.payment.amount, result.payment.currency),
    )


@router.post("/verify", response_model=RazorpayVerificationResponse)
def verify_checkout(
    request: RazorpayCheckoutVerificationRequest,
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
    client: RazorpayClientDep,
    _: OperationsPrincipalDep,
) -> RazorpayVerificationResponse:
    """Verify Checkout HMAC, then retrieve and persist authoritative provider state."""
    result = GatewayPaymentService(session, clock, settings, client).verify_checkout(
        order_id=request.razorpay_order_id,
        payment_id=request.razorpay_payment_id,
        signature=request.razorpay_signature,
    )
    session.commit()
    return RazorpayVerificationResponse(
        payment=PaymentRead.from_model(result.payment),
        verified_provider_status=result.provider_status,
        recovery_case_id=result.case.case_id if result.case else None,
        recovery_case_state=result.case.state.value if result.case else None,
    )


@router.post("/webhooks", response_model=RazorpayWebhookResponse, include_in_schema=False)
async def receive_webhook(
    request: Request,
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
    client: RazorpayClientDep,
    signature: Annotated[str | None, Header(alias="X-Razorpay-Signature")] = None,
    delivery_id: Annotated[str | None, Header(alias="X-Razorpay-Event-Id")] = None,
) -> RazorpayWebhookResponse:
    """Verify the exact request bytes before parsing or persisting a delivery."""
    # Max 64KB limit for webhooks to prevent memory exhaustion attacks
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > 65_536:
        raise GatewaySignatureInvalid()

    raw_body = await request.body()
    if len(raw_body) > 65_536:
        raise GatewaySignatureInvalid()

    result = GatewayPaymentService(session, clock, settings, client).process_webhook(
        raw_body=raw_body,
        signature=signature,
        delivery_id=delivery_id,
    )
    session.commit()
    return RazorpayWebhookResponse(
        duplicate=result.duplicate,
        known_payment=result.known_payment,
        payment_id=result.payment.payment_id if result.payment else None,
        recovery_case_id=result.case.case_id if result.case else None,
    )


__all__ = ["router"]
