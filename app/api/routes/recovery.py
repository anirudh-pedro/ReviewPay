"""Recovery case endpoints (Requirement 24.3).

Thin handlers. The one substantive endpoint, ``POST /recovery/cases/{id}/run``,
delegates a whole recovery cycle to the workflow and serializes what came back
(Requirement 1.9).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import delete, func, select

from app.api.auth import OperationsPrincipalDep
from app.api.deps import ClockDep, PaginationDep, SessionDep, SettingsDep
from app.core.enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    CaseState,
    FailureReason,
    PaymentMethod,
    PaymentStatus,
    WorkflowStage,
)
from app.core.errors import RecordNotFound
from app.models import (
    AuditEvent,
    GatewayPayment,
    Payment,
    PaymentAttempt,
    RecoveryAction,
    RecoveryCase,
    RecoveryOutcome,
)
from app.schemas.common import Money, Page
from app.schemas.customer_recovery import (
    CustomerRecoveryExecutionRequest,
    CustomerRecoveryExecutionResponse,
    CustomerRecoveryViewResponse,
    SendRecoveryEmailRequest,
    SendRecoveryEmailResponse,
    VoiceRecoveryRequest,
    VoiceRecoveryResponse,
    VoiceStatusWebhookResponse,
)
from app.schemas.recovery import (
    AuditEventRead,
    AuditTrailResponse,
    DecisionExplanationRead,
    DiagnosisRead,
    ExecutionResultRead,
    PolicyResultRead,
    RecoveryActionRead,
    RecoveryCaseDetail,
    RecoveryCaseSummary,
    RecoveryOutcomeRead,
    WorkflowRunResponse,
)
from app.services.audit_service import AuditService
from app.services.outcome_verifier import OutcomeVerifier
from app.services.payment_service import PaymentService
from app.services.state_machine import StateMachine
from app.workflows.recovery_workflow import RevenueRecoveryWorkflow

router = APIRouter(prefix="/recovery", tags=["recovery"])


def _get_case(session, case_id: str) -> RecoveryCase:
    case = session.get(RecoveryCase, case_id)
    if case is None:
        raise RecordNotFound("RecoveryCase", case_id)
    return case


def _currency(session, payment_id: str) -> str:
    payment = session.get(Payment, payment_id)
    return payment.currency if payment else "INR"


def _action_read(action: RecoveryAction) -> RecoveryActionRead:
    return RecoveryActionRead(
        action_id=action.action_id,
        action_type=action.action_type,
        estimated_probability=action.estimated_probability,
        confidence=action.confidence,
        model_version=action.model_version,
        expected_recovery_value=action.expected_recovery_value,
        erv_breakdown=action.erv_breakdown or {},
        risk_level=action.risk_level,
        policy_outcome=action.policy_outcome,
        policy_rule_id=action.policy_rule_id,
        policy_reason=action.policy_reason,
        decision_explanation=action.decision_explanation or {},
        status=action.status,
        requires_human_approval=action.requires_human_approval,
        created_at=action.created_at,
        scheduled_at=action.scheduled_at,
        executed_at=action.executed_at,
    )


@router.get("/cases", response_model=Page[RecoveryCaseSummary], summary="List recovery cases")
def list_cases(
    session: SessionDep,
    pagination: PaginationDep,
    state: Annotated[CaseState | None, Query(description="Filter by case state.")] = None,
    real_only: Annotated[bool, Query(description="Filter to only non-synthetic/real gateway cases.")] = False,
) -> Page[RecoveryCaseSummary]:
    from sqlalchemy.orm import selectinload

    total_statement = select(func.count()).select_from(RecoveryCase)
    items_statement = select(RecoveryCase).options(
        selectinload(RecoveryCase.payment).selectinload(Payment.gateway_payment)
    ).order_by(
        RecoveryCase.created_at.desc(), RecoveryCase.case_id
    )

    if real_only:
        total_statement = total_statement.join(Payment, RecoveryCase.payment_id == Payment.payment_id).where(
            Payment.is_synthetic.is_(False)
        )
        items_statement = items_statement.join(Payment, RecoveryCase.payment_id == Payment.payment_id).where(
            Payment.is_synthetic.is_(False)
        )

    if state is not None:
        total_statement = total_statement.where(RecoveryCase.state == state)
        items_statement = items_statement.where(RecoveryCase.state == state)

    total = int(session.execute(total_statement).scalar_one())
    cases = list(
        session.execute(items_statement.limit(pagination.limit).offset(pagination.offset))
        .scalars()
        .all()
    )

    return Page[RecoveryCaseSummary](
        items=[
            RecoveryCaseSummary.from_model(case, _currency(session, case.payment_id))
            for case in cases
        ],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.post("/cases/clear", summary="Clear recovery cases queue")
def clear_cases(session: SessionDep) -> dict[str, Any]:
    """Clear all recovery cases and associated transactions for a fresh demo."""
    session.execute(delete(RecoveryOutcome))
    session.execute(delete(RecoveryAction))
    session.execute(delete(AuditEvent))
    session.execute(delete(RecoveryCase))
    session.execute(delete(PaymentAttempt))
    session.execute(delete(GatewayPayment))
    session.execute(delete(Payment))
    session.commit()
    return {"status": "cleared", "message": "Recovery queue cleared successfully"}


@router.get(
    "/cases/{case_id}",
    response_model=RecoveryCaseDetail,
    summary="Get a recovery case with its decision explanation",
)
def get_case(case_id: str, session: SessionDep) -> RecoveryCaseDetail:
    """Requirement 12.4: returns the explanation for the most recent action."""
    case = _get_case(session, case_id)
    currency = _currency(session, case.payment_id)

    actions = sorted(case.actions, key=lambda item: (item.created_at, item.action_id))
    latest = actions[-1] if actions else None

    explanation = None
    if latest is not None and latest.decision_explanation:
        explanation = DecisionExplanationRead.model_validate(latest.decision_explanation)

    policy = None
    if latest is not None and latest.policy_outcome is not None:
        policy = PolicyResultRead(
            outcome=latest.policy_outcome,
            rule_id=latest.policy_rule_id or "",
            reason=latest.policy_reason or "",
        )

    outcome = None
    if latest is not None and latest.outcome is not None:
        outcome = RecoveryOutcomeRead.model_validate(latest.outcome)

    waiting_until = None
    if latest is not None and latest.scheduled_at is not None and latest.executed_at is None:
        waiting_until = latest.scheduled_at

    summary = RecoveryCaseSummary.from_model(case, currency)
    return RecoveryCaseDetail(
        **summary.model_dump(),
        diagnosis=DiagnosisRead.model_validate(case.diagnosis) if case.diagnosis else None,
        latest_action=_action_read(latest) if latest else None,
        latest_explanation=explanation,
        latest_policy=policy,
        latest_outcome=outcome,
        actions=[_action_read(action) for action in actions],
        waiting_until=waiting_until,
        is_terminal=case.is_terminal,
    )


@router.post(
    "/cases/{case_id}/run",
    response_model=WorkflowRunResponse,
    summary="Run one recovery cycle",
)
def run_case(
    case_id: str,
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
    _: OperationsPrincipalDep,
) -> WorkflowRunResponse:
    """Perform exactly one decide, gate, execute, verify cycle.

    Returns 404 for an unknown case and 409 for a terminal one
    (Requirement 24.8, 24.9).
    """
    _get_case(session, case_id)

    workflow = RevenueRecoveryWorkflow(session=session, clock=clock, settings=settings)
    run = workflow.run(case_id)

    return WorkflowRunResponse(
        workflow_id=run.workflow_id,
        case_id=run.case_id,
        payment_id=run.payment_id,
        started_at=run.started_at,
        ended_at=run.ended_at,
        state=run.state,
        final_status=run.final_status,
        selected_action=run.selected_action,
        explanation=(
            DecisionExplanationRead.model_validate(run.decision.explanation.to_dict())
            if run.decision is not None
            else None
        ),
        policy=(
            PolicyResultRead(
                outcome=run.policy.outcome,
                rule_id=run.policy.rule_id,
                reason=run.policy.reason,
            )
            if run.policy is not None
            else None
        ),
        execution=(
            ExecutionResultRead(
                action=run.execution.action,
                status=run.execution.status,
                provider_response=run.execution.provider_response,
                executed_at=run.execution.executed_at,
            )
            if run.execution is not None
            else None
        ),
        outcome=(
            RecoveryOutcomeRead.model_validate(run.outcome)
            if run.outcome is not None
            else None
        ),
        recovered_amount=Money.of(run.recovered_amount, run.currency),
        waiting_until=run.waiting_until,
        stages=list(run.stages),
        message=run.message,
    )


@router.get(
    "/cases/{case_id}/audit",
    response_model=AuditTrailResponse,
    summary="Get a case's complete audit trail",
)
def get_case_audit(case_id: str, session: SessionDep, clock: ClockDep) -> AuditTrailResponse:
    """Requirement 19.7: oldest first."""
    case = _get_case(session, case_id)
    events = AuditService(session=session, clock=clock).for_case(case.case_id)

    return AuditTrailResponse(
        case_id=case.case_id,
        events=[AuditEventRead.from_model(event) for event in events],
        total=len(events),
    )


@router.get(
    "/cases/{case_id}/customer-view",
    response_model=CustomerRecoveryViewResponse,
    summary="Get customer-facing recovery view",
)
def get_customer_recovery_view(
    case_id: str,
    session: SessionDep,
) -> CustomerRecoveryViewResponse:
    """Public customer-safe view explaining failure and presenting recovery options."""
    case = _get_case(session, case_id)
    payment = session.get(Payment, case.payment_id)
    if payment is None:
        raise RecordNotFound("Payment", case.payment_id)

    actions = sorted(case.actions, key=lambda a: (a.created_at, a.action_id))
    latest_action = actions[-1] if actions else None
    action_type = latest_action.action_type if latest_action else ActionType.SEND_PAYMENT_LINK

    reason = None
    if case.diagnosis and isinstance(case.diagnosis, dict):
        diag_reason = case.diagnosis.get("failure_reason")
        if diag_reason:
            try:
                reason = FailureReason(diag_reason)
            except ValueError:
                pass
    if reason is None:
        reason = payment.failure_reason or FailureReason.BANK_TIMEOUT

    reason_details = {
        FailureReason.BANK_TIMEOUT: (
            "Temporary Bank Processing Timeout",
            f"Your issuing bank ({payment.payment_method.value.upper()}) was momentarily unreachable. No money was deducted from your account.",
            "UPI_QR",
            "Instant UPI Payment Link",
            "Scan the dynamic UPI QR code with GPay, PhonePe, or Paytm, or authorize a 1-click retry.",
        ),
        FailureReason.INSUFFICIENT_FUNDS: (
            "Account Balance Issue",
            "The bank returned an insufficient balance status for the selected account. You can complete this payment using another card or UPI account.",
            "ALTERNATIVE_PAYMENT",
            "Alternative Payment Method",
            "Select an alternative payment method (Card / UPI) to complete your order without starting over.",
        ),
        FailureReason.NETWORK_ERROR: (
            "Connection Interrupted",
            "The 3D-Secure authentication handshake timed out between the gateway and your bank. The payment link below is active and ready.",
            "SMART_RETRY",
            "1-Click Verified Retry",
            "The gateway connection has been restored. Tap below to retry the transaction immediately.",
        ),
        FailureReason.EXPIRED_CARD: (
            "Card Declined by Issuer",
            "Your card could not be billed by the card network. RevivePay has prepared alternative payment channels for your order.",
            "ALTERNATIVE_PAYMENT",
            "Switch to UPI or New Card",
            "Choose another card or pay instantly with UPI to keep your order active.",
        ),
        FailureReason.CHECKOUT_ABANDONMENT: (
            "Checkout Session Saved",
            "Your previous checkout session was closed before completion. RevivePay preserved your cart and order amount.",
            "UPI_QR",
            "Resume Payment Session",
            "Scan to complete your payment or choose your preferred checkout method.",
        ),
    }

    title, explanation, ui_action, sol_title, sol_desc = reason_details.get(
        reason,
        (
            "Payment Incomplete",
            "Your previous payment attempt was interrupted. Your order has been held securely.",
            "UPI_QR",
            "Instant Payment Recovery",
            "Complete your payment below to confirm your order.",
        ),
    )

    amount_inr = f"{payment.amount / 100:.2f}"
    upi_payload = f"upi://pay?pa=revivepay@razorpay&pn=Demo+Merchant&am={amount_inr}&cu=INR&tr={payment.payment_id}"

    current_status = (
        "RECOVERED"
        if case.state == CaseState.RECOVERED or payment.status == PaymentStatus.SUCCEEDED
        else "PENDING_RECOVERY"
    )

    return CustomerRecoveryViewResponse(
        case_id=case.case_id,
        payment_id=payment.payment_id,
        merchant_name="Buildathon Demo Store",
        amount=Money.of(payment.amount, payment.currency),
        status=current_status,
        failure_reason=reason,
        failure_title=title,
        failure_explanation=explanation,
        recommended_action=action_type,
        solution_title=sol_title,
        solution_description=sol_desc,
        action_type=ui_action,
        available_methods=["UPI", "Card", "Netbanking"],
        simulated_upi_qr=upi_payload,
        cooldown_seconds=0,
        expires_at=None,
    )


@router.post(
    "/cases/{case_id}/customer-recover",
    response_model=CustomerRecoveryExecutionResponse,
    summary="Process customer payment recovery",
)
def customer_complete_recovery(
    case_id: str,
    request: CustomerRecoveryExecutionRequest,
    session: SessionDep,
    clock: ClockDep,
) -> CustomerRecoveryExecutionResponse:
    """Process customer payment recovery through the recovery portal."""
    case = _get_case(session, case_id)
    payment = session.get(Payment, case.payment_id)
    if payment is None:
        raise RecordNotFound("Payment", case.payment_id)

    now = clock.now()
    method_name = request.selected_method.upper()
    payment_method = (
        PaymentMethod.UPI
        if "UPI" in method_name
        else PaymentMethod.CARD
        if "CARD" in method_name
        else PaymentMethod.NETBANKING
    )

    # Record successful recovery attempt
    attempt = PaymentService(session, clock).record_recovery_attempt(
        payment=payment,
        status=PaymentStatus.SUCCEEDED,
        action=ActionType.SEND_PAYMENT_LINK,
        failure_reason=None,
        provider_response={
            "recovered_by": "customer_portal",
            "method": payment_method.value,
            "details": request.instrument_details,
            "timestamp": now.isoformat(),
        },
    )

    # Advance state machine to RECOVERED safely
    sm = StateMachine(clock)
    if case.state in (CaseState.FAILED, CaseState.SCHEDULED):
        for st in [
            CaseState.DIAGNOSING,
            CaseState.DIAGNOSED,
            CaseState.EVALUATING,
            CaseState.DECISION_READY,
            CaseState.POLICY_CHECK,
            CaseState.APPROVED,
            CaseState.EXECUTING,
            CaseState.VERIFYING,
            CaseState.RECOVERED,
        ]:
            case = sm.transition(case, st)
    elif case.state != CaseState.RECOVERED:
        case.state = CaseState.RECOVERED
        case.updated_at = now

    actions = sorted(case.actions, key=lambda a: (a.created_at, a.action_id))
    latest_action = actions[-1] if actions else None
    if latest_action is not None and latest_action.outcome is not None:
        latest_action.outcome.recovered = True
        latest_action.outcome.recovered_amount = int(payment.amount)
        latest_action.outcome.new_payment_status = PaymentStatus.SUCCEEDED
        latest_action.outcome.failure_reason = None
        latest_action.outcome.verification_timestamp = now
        latest_action.status = ActionStatus.EXECUTED
    elif latest_action is not None:
        OutcomeVerifier(session, clock).verify(
            latest_action,
            previous_status=PaymentStatus.FAILED,
            audit=AuditService(session, clock),
        )

    # Always record the revenue recovery audit event
    AuditService(session, clock).record(
        case_id=case.case_id,
        payment_id=payment.payment_id,
        stage=WorkflowStage.VERIFICATION,
        event_type=AuditEventType.REVENUE_RECOVERED,
        message=f"Customer completed recovery payment of {payment.amount} {payment.currency} via {payment_method.value} portal.",
        metadata={
            "recovered_amount": payment.amount,
            "currency": payment.currency,
            "payment_method": payment_method.value,
            "attempt_id": attempt.attempt_id,
            "actor": "customer_portal",
        },
    )

    session.commit()

    receipt_id = f"rcpt_revive_{now.strftime('%Y%m%d%H%M%S')}"

    return CustomerRecoveryExecutionResponse(
        success=True,
        receipt_id=receipt_id,
        case_id=case.case_id,
        payment_id=payment.payment_id,
        amount_recovered=Money.of(payment.amount, payment.currency),
        recovered_at=now.isoformat(),
        message="Payment verified and successfully recovered via RevivePay!",
    )


@router.post(
    "/cases/{case_id}/send-email",
    response_model=SendRecoveryEmailResponse,
    summary="Send a live recovery email to customer",
)
def send_recovery_email(
    case_id: str,
    payload: SendRecoveryEmailRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> SendRecoveryEmailResponse:
    """Send a live transactional payment recovery email via Resend, SendGrid, or SMTP."""
    from urllib.parse import quote
    from app.services.email_service import EmailRecoveryService

    case = _get_case(session, case_id)
    payment = case.payment or session.get(Payment, case.payment_id)
    amount_formatted = f"₹{case.amount_at_risk / 100:.2f} INR"
    failure_reason = (
        payment.failure_reason.value if payment and payment.failure_reason else "Payment Interruption"
    )

    gw = payment.gateway_payment if payment else None
    order_id = gw.provider_order_id if gw else (case.payment_id or case_id)

    base_url = (payload.portal_base_url or "http://localhost:5173").rstrip("/")
    recovery_url = f"{base_url}/recover/{case_id}"

    service = EmailRecoveryService(settings)
    result = service.send_recovery_email(
        recipient_email=payload.recipient_email,
        customer_name=payload.customer_name,
        amount_formatted=amount_formatted,
        failure_reason_text=failure_reason.replace("_", " ").title(),
        recovery_url=recovery_url,
        order_id=order_id,
    )

    # Pre-build mailto URL for immediate browser/client fallback
    subject = quote(f"Finish your payment of {amount_formatted} ({order_id})")
    body = quote(
        f"Hi {payload.customer_name},\n\n"
        f"Your payment of {amount_formatted} was interrupted. Use the secure link below to complete your checkout with 1-click UPI:\n\n"
        f"{recovery_url}\n\n"
        f"Order Reference: {order_id}\n"
        f"— RevivePay Recovery"
    )
    mailto_url = f"mailto:{payload.recipient_email}?subject={subject}&body={body}"

    return SendRecoveryEmailResponse(
        success=result.success,
        provider=result.provider,
        recipient=result.recipient,
        message=result.message,
        message_id=result.message_id,
        mailto_fallback_url=mailto_url,
        error=result.error,
    )


@router.post(
    "/cases/{case_id}/voice",
    response_model=VoiceRecoveryResponse,
    summary="Initiate Exotel outbound voice recovery call",
)
def trigger_voice_recovery(
    case_id: str,
    payload: VoiceRecoveryRequest,
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> VoiceRecoveryResponse:
    from app.services.voice_recovery import VoiceRecoveryService

    service = VoiceRecoveryService(session=session, clock=clock, settings=settings)
    result = service.trigger_voice_recovery(
        case_id=case_id,
        customer_phone=payload.customer_phone,
        customer_name=payload.customer_name,
        portal_base_url=payload.portal_base_url,
    )

    return VoiceRecoveryResponse(**result)


@router.post(
    "/voice/webhook",
    response_model=VoiceStatusWebhookResponse,
    summary="Exotel outbound call status callback",
)
async def exotel_voice_webhook(
    request: Request,
    session: SessionDep,
    clock: ClockDep,
) -> VoiceStatusWebhookResponse:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception:
            data = {}
    else:
        try:
            form = await request.form()
            data = dict(form)
        except Exception:
            data = {}

    call_id = str(data.get("CallSid") or data.get("CallId") or data.get("Sid") or "")
    status_str = str(data.get("Status") or data.get("CallStatus") or "").lower()
    case_id = str(data.get("CustomField") or "")

    if not case_id and call_id:
        actions = session.execute(
            select(RecoveryAction).where(RecoveryAction.action_type == ActionType.VOICE_CALL)
        ).scalars().all()
        for act in actions:
            if act.decision_explanation and act.decision_explanation.get("call_id") == call_id:
                case_id = act.case_id
                break

    if case_id:
        case = session.get(RecoveryCase, case_id)
        if case:
            audit = AuditService(session, clock)
            if status_str in ("in-progress", "answered"):
                audit.record(
                    case_id=case.case_id,
                    payment_id=case.payment_id,
                    stage=WorkflowStage.EXECUTION,
                    event_type=AuditEventType.VOICE_CALL_ANSWERED,
                    message=f"Exotel voice call answered by customer (Call SID: {call_id}).",
                    metadata={"call_id": call_id, "status": status_str},
                )
            elif status_str in ("completed",):
                audit.record(
                    case_id=case.case_id,
                    payment_id=case.payment_id,
                    stage=WorkflowStage.EXECUTION,
                    event_type=AuditEventType.VOICE_CALL_COMPLETED,
                    message=f"Exotel voice call completed (Call SID: {call_id}).",
                    metadata={"call_id": call_id, "status": status_str},
                )
            elif status_str in ("failed", "busy", "no-answer", "canceled"):
                audit.record(
                    case_id=case.case_id,
                    payment_id=case.payment_id,
                    stage=WorkflowStage.EXECUTION,
                    event_type=AuditEventType.VOICE_CALL_FAILED,
                    message=f"Exotel voice call ended with status '{status_str}' (Call SID: {call_id}).",
                    metadata={"call_id": call_id, "status": status_str},
                )
            session.commit()

    return VoiceStatusWebhookResponse(
        received=True,
        case_id=case_id or None,
        call_id=call_id or None,
        status=status_str or None,
    )


__all__ = ["router"]
