"""Judge Demo pipeline service.

Executes the full 8-stage RevivePay recovery journey with transparent proof labels:
1. Evidence (Razorpay Gateway or Synthetic Payment) -> [REAL RAZORPAY SANDBOX] or [SYNTHETIC SIMULATION]
2. AI Diagnosis + Confidence -> [AI COPILOT ADVISORY]
3. Copilot Strategy Recommendation
4. ERV Calculation & Alternative Ranking
5. PolicyEngine Safety Verdict -> [POLICY GATE - FINAL AUTHORITY]
6. Bounded Execution -> [SIMULATED EXECUTOR]
7. Independent Verification -> [OUTCOME VERIFIER]
8. Audit Trail & Revenue Recovery Summary
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings, get_settings
from app.core.enums import CaseState, PolicyOutcome
from app.core.errors import RecordNotFound
from app.models import GatewayPayment, Payment, RecoveryCase
from app.services.candidate_generator import RecoveryActionCandidateGenerator
from app.services.context_builder import RecoveryContextBuilder
from app.services.copilot import AICopilotService, CopilotAnalysis
from app.services.expected_value import ExpectedRecoveryCalculator
from app.services.policy_engine import PolicyEngine
from app.workflows.recovery_workflow import RevenueRecoveryWorkflow


@dataclass(frozen=True)
class JudgeDemoStage:
    stage_number: int
    name: str
    label: str  # "REAL RAZORPAY SANDBOX" | "AI COPILOT ADVISORY" | "POLICY GATE - MANDATORY AUTHORITY" | "SIMULATED EXECUTOR" | "OUTCOME VERIFIER"
    status: str  # "PASSED" | "BLOCKED" | "ESCALATED" | "INFO"
    detail: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class JudgeDemoResult:
    case_id: str
    payment_id: str
    amount: int
    currency: str
    evidence_source: str  # "razorpay_sandbox" or "synthetic_simulation"
    is_real_razorpay: bool
    razorpay_order_id: str | None
    razorpay_payment_id: str | None
    
    # Copilot analysis
    ai_root_cause: str
    ai_confidence: float
    ai_recommended_action: str
    ai_reasoning: str
    
    # Selected action & ERV
    selected_action: str | None
    expected_recovery_value: int | None
    gross_recovery: int | None
    intervention_cost: int | None
    friction_penalty: int | None
    
    # Policy check
    policy_outcome: str | None
    policy_rule_id: str | None
    policy_reason: str | None
    
    # Execution & Verification
    final_case_state: str
    execution_status: str | None
    recovered_amount: int
    is_recovered: bool
    
    stages: tuple[JudgeDemoStage, ...]


class JudgeDemoService:
    """Orchestrates and formats a case evaluation for judge presentation."""

    def __init__(
        self,
        session: Session,
        clock: VirtualClock,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._settings = settings or get_settings()
        self._workflow = RevenueRecoveryWorkflow(session=session, clock=clock, settings=self._settings)
        self._copilot = AICopilotService(settings=self._settings)
        self._calculator = ExpectedRecoveryCalculator(self._settings)

    def run_judge_demo(self, case_id: str) -> JudgeDemoResult:
        """Run one complete recovery workflow cycle and capture all 8 proof stages."""
        case = self._session.get(RecoveryCase, case_id)
        if case is None:
            raise RecordNotFound("RecoveryCase", case_id)

        payment = self._session.get(Payment, case.payment_id)
        if payment is None:
            raise RecordNotFound("Payment", case.payment_id)

        # Check for associated Razorpay Gateway Order mapping
        gateway_payment = self._session.execute(
            select(GatewayPayment).where(GatewayPayment.payment_id == payment.payment_id)
        ).scalar_one_or_none()

        is_real_razorpay = gateway_payment is not None
        evidence_source = "Razorpay Sandbox Gateway (HMAC Verified)" if is_real_razorpay else "Synthetic Payment Simulation"
        label_evidence = "REAL RAZORPAY SANDBOX" if is_real_razorpay else "SYNTHETIC SIMULATION"

        # Stage 1: Evidence
        stage1 = JudgeDemoStage(
            stage_number=1,
            name="Payment & Risk Evidence",
            label=label_evidence,
            status="PASSED",
            detail=f"Payment {payment.payment_id} for {payment.amount} {payment.currency} minor units at risk. Cause: {payment.failure_reason.value if payment.failure_reason else 'UNKNOWN'}.",
            payload={
                "payment_id": payment.payment_id,
                "amount": payment.amount,
                "currency": payment.currency,
                "failure_reason": payment.failure_reason.value if payment.failure_reason else "UNKNOWN",
                "payment_method": payment.payment_method.value,
                "gateway_order_id": gateway_payment.provider_order_id if gateway_payment else None,
                "gateway_payment_id": gateway_payment.provider_payment_id if gateway_payment else None,
                "is_real_razorpay": is_real_razorpay,
            },
        )

        # Build recovery context for copilot & workflow
        builder = RecoveryContextBuilder(self._session, self._clock)
        context = builder.build(case)
        
        # Stage 2 & 3: Copilot Analysis & Recommendation
        copilot_res: CopilotAnalysis = self._copilot.analyze(context)

        stage2 = JudgeDemoStage(
            stage_number=2,
            name="AI Copilot Root Cause Diagnosis & Confidence",
            label="AI COPILOT ADVISORY",
            status="PASSED",
            detail=f"Root cause: {copilot_res.root_cause} (Severity: {copilot_res.severity}). Confidence: {copilot_res.confidence:.0%}.",
            payload={
                "root_cause": copilot_res.root_cause,
                "severity": copilot_res.severity,
                "confidence": copilot_res.confidence,
                "explanation": copilot_res.explanation,
                "fallback_used": copilot_res.fallback_used,
                "provider": copilot_res.provider_name,
            },
        )

        stage3 = JudgeDemoStage(
            stage_number=3,
            name="AI Strategy Recommendation",
            label="AI COPILOT ADVISORY",
            status="PASSED",
            detail=f"Recommended action: {copilot_res.recommended_action.value}. Rationale: {copilot_res.strategic_reasoning}",
            payload={
                "recommended_action": copilot_res.recommended_action.value,
                "strategic_reasoning": copilot_res.strategic_reasoning,
                "key_risk_factors": list(copilot_res.key_risk_factors),
            },
        )

        # Stage 4-7: Workflow Execution (Decide, Policy, Execute, Verify)
        # Check if case is terminal before running
        if case.state in CaseState.terminal():
            # If already ran, pull latest run data from case actions
            actions = sorted(case.actions, key=lambda x: x.created_at)
            latest_action = actions[-1] if actions else None
            
            selected_act = latest_action.action_type.value if latest_action else None
            policy_out = latest_action.policy_outcome.value if latest_action and latest_action.policy_outcome else "APPROVED"
            policy_rule = latest_action.policy_rule_id if latest_action else "default_approve"
            policy_reason = latest_action.policy_reason if latest_action else "Case already completed."
            
            erv_val = latest_action.expected_recovery_value if latest_action else 0
            erv_breakdown = latest_action.erv_breakdown or {}
            
            rec_amount = latest_action.outcome.recovered_amount if latest_action and latest_action.outcome else 0
            is_rec = latest_action.outcome.recovered if latest_action and latest_action.outcome else False
            exec_status = latest_action.status.value if latest_action else "COMPLETED"
            final_state = case.state.value

        else:
            run_res = self._workflow.run(case.case_id)
            selected_act = run_res.selected_action.value if run_res.selected_action else None
            policy_out = run_res.policy.outcome.value if run_res.policy else None
            policy_rule = run_res.policy.rule_id if run_res.policy else None
            policy_reason = run_res.policy.reason if run_res.policy else None
            
            if run_res.decision:
                erv_val = run_res.decision.expected_recovery_value
                erv_breakdown = run_res.decision.breakdown.to_dict()
            else:
                erv_val = 0
                erv_breakdown = {}

            rec_amount = run_res.recovered_amount
            is_rec = run_res.final_status is CaseState.RECOVERED
            exec_status = run_res.execution.status.value if run_res.execution else None
            final_state = run_res.final_status.value

        stage4 = JudgeDemoStage(
            stage_number=4,
            name="Expected Recovery Value (ERV) Valuation & Ranking",
            label="REVIVEPAY ERV ENGINE",
            status="PASSED",
            detail=f"Evaluated ERV: {erv_val} minor units for action {selected_act}.",
            payload=erv_breakdown,
        )

        stage5_status = "BLOCKED" if policy_out == "BLOCKED" else "ESCALATED" if policy_out == "ESCALATED" else "PASSED"
        stage5 = JudgeDemoStage(
            stage_number=5,
            name="Mandatory PolicyEngine Security Gate",
            label="POLICY GATE - MANDATORY AUTHORITY",
            status=stage5_status,
            detail=f"Verdict: {policy_out} by rule '{policy_rule}'. Reason: {policy_reason}",
            payload={
                "outcome": policy_out,
                "rule_id": policy_rule,
                "reason": policy_reason,
                "final_authority": True,
            },
        )

        stage6_status = "PASSED" if exec_status == "SUCCEEDED" else "INFO" if exec_status is None else "BLOCKED"
        stage6 = JudgeDemoStage(
            stage_number=6,
            name="Bounded Action Execution",
            label="SIMULATED EXECUTOR",
            status=stage6_status,
            detail=f"Executor status: {exec_status or 'SKIPPED_BY_POLICY'}.",
            payload={
                "selected_action": selected_act,
                "execution_status": exec_status,
                "executor_type": "PaymentSimulatorExecutor",
            },
        )

        stage7 = JudgeDemoStage(
            stage_number=7,
            name="Independent Outcome Verification",
            label="OUTCOME VERIFIER",
            status="PASSED" if is_rec else "INFO",
            detail=f"Independent state re-read confirmed recovered={is_rec}. Amount: {rec_amount} {payment.currency} minor units.",
            payload={
                "recovered": is_rec,
                "recovered_amount": rec_amount,
                "verification_method": "Payment DB re-read (ignores executor claims)",
            },
        )

        stage8 = JudgeDemoStage(
            stage_number=8,
            name="Audit Trail & Final Revenue Summary",
            label="AUDIT & METRICS",
            status="PASSED",
            detail=f"Final case state: {final_state}. ₹ Recovered: {rec_amount / 100:.2f} {payment.currency}.",
            payload={
                "final_state": final_state,
                "recovered_rupees": rec_amount / 100.0,
                "case_id": case.case_id,
            },
        )

        return JudgeDemoResult(
            case_id=case.case_id,
            payment_id=payment.payment_id,
            amount=int(payment.amount),
            currency=payment.currency,
            evidence_source=evidence_source,
            is_real_razorpay=is_real_razorpay,
            razorpay_order_id=gateway_payment.provider_order_id if gateway_payment else None,
            razorpay_payment_id=gateway_payment.provider_payment_id if gateway_payment else None,
            ai_root_cause=copilot_res.root_cause,
            ai_confidence=copilot_res.confidence,
            ai_recommended_action=copilot_res.recommended_action.value,
            ai_reasoning=copilot_res.strategic_reasoning,
            selected_action=selected_act,
            expected_recovery_value=erv_val,
            gross_recovery=erv_breakdown.get("gross_expected_recovery"),
            intervention_cost=erv_breakdown.get("intervention_cost"),
            friction_penalty=erv_breakdown.get("customer_friction_penalty"),
            policy_outcome=policy_out,
            policy_rule_id=policy_rule,
            policy_reason=policy_reason,
            final_case_state=final_state,
            execution_status=exec_status,
            recovered_amount=rec_amount,
            is_recovered=is_rec,
            stages=(stage1, stage2, stage3, stage4, stage5, stage6, stage7, stage8),
        )


__all__ = ["JudgeDemoResult", "JudgeDemoService", "JudgeDemoStage"]
