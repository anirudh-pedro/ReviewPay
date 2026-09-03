"""Voice Recovery Service orchestrating Exotel outbound calls.

Architecture Invariants:
- AI recommends. Policy decides. Executor acts. Verification proves.
- The voice channel must never bypass the PolicyEngine.
- An answered call is NOT a recovery.
- Strict budget limits, idempotency guards, and terminal state checks.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings, get_settings
from app.core.enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    CaseState,
    PaymentStatus,
    PolicyOutcome,
    RiskLevel,
    WorkflowStage,
)
from app.core.errors import RecordNotFound, RevivePayError
from app.core.logging import get_logger
from app.db.base import new_id
from app.models import Payment, RecoveryAction, RecoveryCase
from app.services.audit_service import AuditService
from app.services.context_builder import RecoveryContextBuilder
from app.services.decision_engine import DecisionExplanation, RecoveryDecision
from app.services.expected_value import ExpectedValueBreakdown
from app.services.exotel_client import ExotelCallResult, ExotelClient
from app.services.policy_engine import PolicyEngine

logger = get_logger("voice_recovery")


class VoiceRecoveryError(RevivePayError):
    """Voice recovery execution or policy failure."""

    code = "VOICE_RECOVERY_ERROR"
    http_status = 400


class VoiceRecoveryService:
    """Bounded, policy-gated voice recovery execution service."""

    def __init__(
        self,
        session: Session,
        clock: VirtualClock,
        settings: Settings | None = None,
        exotel_client: ExotelClient | None = None,
        policy_engine: PolicyEngine | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self.session = session
        self.clock = clock
        self.settings = settings or get_settings()
        self.exotel_client = exotel_client or ExotelClient(self.settings)
        self.policy_engine = policy_engine or PolicyEngine(
            self.settings, supported_actions=frozenset(ActionType)
        )
        self.audit = audit_service or AuditService(session, clock)
 
    def trigger_voice_recovery(
        self,
        case_id: str,
        customer_phone: str,
        customer_name: str = "Valued Customer",
        portal_base_url: str = "http://localhost:5173",
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        """Execute a bounded voice recovery action through Exotel."""
        case = self.session.get(RecoveryCase, case_id)
        if case is None:
            raise RecordNotFound("RecoveryCase", case_id)

        payment = case.payment or self.session.get(Payment, case.payment_id)
        if payment is None:
            raise RecordNotFound("Payment", case.payment_id)

        # 1. State & Lifecycle Safety Gates
        if case.state == CaseState.RECOVERED or payment.status in PaymentStatus.successful():
            raise VoiceRecoveryError(
                f"Cannot initiate voice recovery on an already recovered payment ({case.state.value})."
            )

        if case.state == CaseState.ESCALATED:
            raise VoiceRecoveryError(
                "Case is escalated to human compliance. Automated voice recovery is prohibited."
            )

        # 2. Recovery Budget Safety Gate
        if payment.attempt_count > self.settings.max_automatic_retries:
            self.audit.record(
                case_id=case.case_id,
                payment_id=payment.payment_id,
                stage=WorkflowStage.POLICY,
                event_type=AuditEventType.POLICY_BLOCKED,
                message="Voice recovery blocked: maximum automatic recovery attempts exhausted.",
                metadata={"attempt_count": payment.attempt_count, "limit": self.settings.max_automatic_retries},
            )
            raise VoiceRecoveryError("Automatic recovery attempt budget exhausted.")

        # 3. Idempotency Guard: prevent duplicate active calls
        cutoff = self.clock.now() - timedelta(minutes=5)
        recent_call = self.session.execute(
            select(RecoveryAction).where(
                RecoveryAction.case_id == case.case_id,
                RecoveryAction.action_type == ActionType.VOICE_CALL,
                RecoveryAction.status.in_([ActionStatus.APPROVED, ActionStatus.EXECUTED]),
                RecoveryAction.created_at >= cutoff,
            )
        ).scalars().first()

        recovery_url = f"{portal_base_url.rstrip('/')}/recover/{case.case_id}"

        if recent_call:
            call_sid = recent_call.decision_explanation.get("call_id", "ACTIVE_CALL")
            return {
                "case_id": case.case_id,
                "channel": "VOICE",
                "status": "CALL_ALREADY_ACTIVE",
                "call_id": call_sid,
                "payment_link": recovery_url,
                "policy_decision": "APPROVED",
                "message": "An active voice recovery call is already in progress for this case.",
                "success": True,
            }

        # 4. Mandatory PolicyEngine Gate
        context = RecoveryContextBuilder(self.session, self.clock).build(case)
        breakdown = ExpectedValueBreakdown(
            action=ActionType.VOICE_CALL,
            recovery_probability=0.85,
            payment_amount=case.amount_at_risk,
            gross_expected_recovery=int(case.amount_at_risk * 0.85),
            intervention_cost=0,
            customer_friction_penalty=0,
            expected_recovery_value=int(case.amount_at_risk * 0.85),
        )
        explanation = DecisionExplanation(
            selected_action=ActionType.VOICE_CALL,
            reason=f"Voice outreach recommended for high-priority {context.failure_reason.value} recovery.",
            probability=0.85,
            expected_recovery_value=int(case.amount_at_risk * 0.85),
            confidence=0.92,
            alternatives=(),
        )
        decision = RecoveryDecision(
            selected_action=ActionType.VOICE_CALL,
            probability=0.85,
            confidence=0.92,
            expected_recovery_value=int(case.amount_at_risk * 0.85),
            breakdown=breakdown,
            risk_level=RiskLevel.MEDIUM,
            model_version="exotel_voice_v1",
            ranked=(),
            explanation=explanation,
        )

        policy_result = self.policy_engine.evaluate(context, decision)

        self.audit.record(
            case_id=case.case_id,
            payment_id=payment.payment_id,
            stage=WorkflowStage.POLICY,
            event_type=AuditEventType.VOICE_POLICY_CHECKED,
            message=f"Policy verdict for voice recovery: {policy_result.outcome.value} (rule: {policy_result.rule_id}).",
            metadata={
                "outcome": policy_result.outcome.value,
                "rule_id": policy_result.rule_id,
                "reason": policy_result.reason,
            },
        )

        if policy_result.outcome != PolicyOutcome.APPROVED:
            raise VoiceRecoveryError(
                f"PolicyEngine rejected voice recovery: {policy_result.outcome.value} ({policy_result.reason})"
            )

        # 5. Audit Request
        self.audit.record(
            case_id=case.case_id,
            payment_id=payment.payment_id,
            stage=WorkflowStage.EXECUTION,
            event_type=AuditEventType.VOICE_RECOVERY_REQUESTED,
            message=f"Voice recovery requested for recipient {customer_phone[:3]}****.",
            metadata={"channel": "VOICE", "phone_masked": f"{customer_phone[:3]}****"},
        )

        # 6. Execute Call via Exotel
        call_result: ExotelCallResult = self.exotel_client.initiate_outbound_call(
            to_phone=customer_phone,
            case_id=case.case_id,
            callback_url=callback_url,
        )

        now = self.clock.now()

        # 7. Record Action and Audit Result
        action = RecoveryAction(
            action_id=new_id("act"),
            case_id=case.case_id,
            payment_id=payment.payment_id,
            action_type=ActionType.VOICE_CALL,
            estimated_probability=0.85,
            confidence=0.92,
            model_version="exotel_voice_v1",
            expected_recovery_value=int(case.amount_at_risk * 0.85),
            erv_breakdown={
                "gross_expected_recovery": case.amount_at_risk,
                "recovery_probability": 0.85,
                "expected_recovery_value": int(case.amount_at_risk * 0.85),
            },
            risk_level=RiskLevel.MEDIUM,
            policy_outcome=policy_result.outcome,
            policy_rule_id=policy_result.rule_id,
            policy_reason=policy_result.reason,
            decision_explanation={
                "channel": "VOICE",
                "call_id": call_result.call_id,
                "status": call_result.status,
                "message": call_result.message,
                "payment_link": recovery_url,
            },
            status=ActionStatus.EXECUTED if call_result.success else ActionStatus.FAILED,
            created_at=now,
            executed_at=now if call_result.success else None,
        )

        self.session.add(action)

        if call_result.success:
            self.audit.record(
                case_id=case.case_id,
                payment_id=payment.payment_id,
                stage=WorkflowStage.EXECUTION,
                event_type=AuditEventType.VOICE_CALL_INITIATED,
                message=f"Exotel outbound voice recovery call placed. Call SID: {call_result.call_id}.",
                metadata={
                    "call_id": call_result.call_id,
                    "status": call_result.status,
                    "action_id": action.action_id,
                },
            )
        else:
            self.audit.record(
                case_id=case.case_id,
                payment_id=payment.payment_id,
                stage=WorkflowStage.EXECUTION,
                event_type=AuditEventType.VOICE_CALL_FAILED,
                message=f"Exotel outbound call failed: {call_result.message}",
                metadata={"error": call_result.error, "status": call_result.status},
            )

        self.session.commit()

        return {
            "case_id": case.case_id,
            "channel": "VOICE",
            "status": "CALL_INITIATED" if call_result.success else "CALL_FAILED",
            "call_id": call_result.call_id,
            "payment_link": recovery_url,
            "policy_decision": policy_result.outcome.value,
            "message": call_result.message,
            "success": call_result.success,
            "error": call_result.error,
        }
