"""Payment endpoints (Requirement 24.2).

Handlers validate, delegate, and serialize. No recovery logic lives here
(Requirement 1.9).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import ClockDep, PaginationDep, SessionDep
from app.core.enums import PaymentStatus
from app.schemas.common import Page
from app.schemas.payment import (
    FailPaymentRequest,
    FailPaymentResponse,
    PaymentDetail,
    PaymentRead,
    SimulatePaymentRequest,
)
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("", response_model=Page[PaymentRead], summary="List payments")
def list_payments(
    session: SessionDep,
    clock: ClockDep,
    pagination: PaginationDep,
    payment_status: Annotated[
        PaymentStatus | None, Query(alias="status", description="Filter by payment status.")
    ] = None,
) -> Page[PaymentRead]:
    page = PaymentService(session, clock).list_payments(
        limit=pagination.limit,
        offset=pagination.offset,
        status=payment_status,
    )
    return Page[PaymentRead](
        items=[PaymentRead.from_model(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{payment_id}",
    response_model=PaymentDetail,
    summary="Get one payment with its attempt history",
)
def get_payment(payment_id: str, session: SessionDep, clock: ClockDep) -> PaymentDetail:
    payment = PaymentService(session, clock).get_payment_with_attempts(payment_id)
    return PaymentDetail.from_model(payment)


@router.post(
    "/simulate",
    response_model=PaymentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a synthetic payment",
)
def simulate_payment(
    request: SimulatePaymentRequest, session: SessionDep, clock: ClockDep
) -> PaymentRead:
    payment = PaymentService(session, clock).create_payment(
        amount=request.amount,
        currency=request.currency,
        payment_method=request.payment_method,
        status=request.status,
        failure_reason=request.failure_reason,
        customer_id=request.customer_id,
        merchant_id=request.merchant_id,
        metadata=request.metadata,
    )
    return PaymentRead.from_model(payment)


@router.post(
    "/{payment_id}/fail",
    response_model=FailPaymentResponse,
    summary="Fail a payment and open a recovery case",
)
def fail_payment(
    payment_id: str,
    request: FailPaymentRequest,
    session: SessionDep,
    clock: ClockDep,
) -> FailPaymentResponse:
    """Fail a payment, then detect revenue risk for it.

    Detection is a separate concern: this handler records the failure and asks the
    risk detector whether a recovery case is warranted (Requirement 4.2, 5.2).
    """
    from app.schemas.common import Money
    from app.services.audit_service import AuditService
    from app.services.risk_detector import RiskDetector

    service = PaymentService(session, clock)
    payment = service.fail_payment(payment_id, request.failure_reason)

    detector = RiskDetector(
        session=session,
        clock=clock,
        audit=AuditService(session=session, clock=clock),
    )
    case = detector.detect_and_open_case(payment)
    session.commit()

    return FailPaymentResponse(
        payment=PaymentRead.from_model(payment),
        case_id=case.case_id if case else None,
        case_state=case.state.value if case else None,
        amount_at_risk=Money.of(case.amount_at_risk, payment.currency) if case else None,
    )
