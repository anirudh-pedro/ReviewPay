"""Razorpay Sandbox order, verification, and signed-webhook endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request, status
from sqlalchemy import select

from app.api.auth import OperationsPrincipalDep
from app.api.deps import ClockDep, RazorpayClientDep, SessionDep, SettingsDep
from app.core.enums import FailureReason, PaymentMethod, PaymentStatus
from app.core.errors import RecordNotFound
from app.models import GatewayPayment
from app.schemas.common import Money
from app.schemas.gateway import (
    GatewayFailureSimulationRequest,
    GatewayFailureSimulationResponse,
    RazorpayCheckoutVerificationRequest,
    RazorpayOrderCreateRequest,
    RazorpayOrderResponse,
    RazorpayVerificationResponse,
    RazorpayWebhookResponse,
)
from app.schemas.payment import PaymentRead
from app.services.audit_service import AuditService
from app.services.gateway_payment_service import GatewayPaymentService, GatewaySignatureInvalid
from app.services.payment_service import PaymentService
from app.services.risk_detector import RiskDetector
from app.workflows.recovery_workflow import RevenueRecoveryWorkflow

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


@router.post(
    "/orders/{order_id}/simulate-failure",
    response_model=GatewayFailureSimulationResponse,
    summary="Simulate a payment failure on a Razorpay Sandbox order and hand over to RevivePay",
)
def simulate_order_failure(
    order_id: str,
    request: GatewayFailureSimulationRequest,
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
    _: OperationsPrincipalDep,
) -> GatewayFailureSimulationResponse:
    """Simulate a transaction outcome/failure scenario on a real Sandbox order.
    
    RevivePay immediately takes over:
    1. Detects risk and opens recovery case.
    2. Diagnoses root cause via AI Recovery Copilot.
    3. Calculates Expected Recovery Value (ERV).
    4. Evaluates PolicyEngine rules.
    5. Executes bounded recovery action and generates customer recovery path.
    """
    mapping = session.execute(
        select(GatewayPayment).where(GatewayPayment.provider_order_id == order_id)
    ).scalar_one_or_none()
    if mapping is None:
        raise RecordNotFound("GatewayOrder", order_id)

    payment = mapping.payment
    method_str = request.payment_method.lower()
    payment.payment_method = (
        PaymentMethod.CARD
        if method_str == "card"
        else PaymentMethod.UPI
        if method_str == "upi"
        else PaymentMethod.NETBANKING
    )

    payment_status = (
        PaymentStatus.ABANDONED
        if request.failure_reason is FailureReason.CHECKOUT_ABANDONMENT
        else PaymentStatus.FAILED
    )

    provider_summary = {
        "provider": "razorpay",
        "order_id": order_id,
        "payment_id": f"pay_sim_{clock.now().strftime('%Y%m%d%H%M%S')}",
        "status": "failed",
        "normalized_failure_reason": request.failure_reason.value,
        "error_description": request.error_description or f"Simulated failure: {request.failure_reason.value}",
        "event_type": "checkout.failure",
    }

    PaymentService(session, clock).record_external_checkout_attempt(
        payment=payment,
        status=payment_status,
        failure_reason=request.failure_reason,
        provider_response=provider_summary,
    )

    case = RiskDetector(
        session=session,
        clock=clock,
        audit=AuditService(session=session, clock=clock),
    ).detect_and_open_case(payment)
    session.flush()

    # RevivePay autonomous takeover: run 1 cycle of RevenueRecoveryWorkflow
    workflow = RevenueRecoveryWorkflow(session=session, clock=clock, settings=settings)
    run = workflow.run(case.case_id)
    session.commit()

    return GatewayFailureSimulationResponse(
        payment=PaymentRead.from_model(payment),
        recovery_case_id=case.case_id,
        recovery_case_state=case.state.value,
        failure_reason=request.failure_reason,
        diagnosis_explanation=run.message or f"RevivePay diagnosed {request.failure_reason.value}.",
        selected_action=run.selected_action,
        policy_outcome=run.policy.outcome.value if run.policy else "APPROVED",
        customer_recovery_url=f"/recover/{case.case_id}",
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
