"""Recovery case, decision, and audit schemas (Requirement 24.3, 24.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    CaseState,
    ExecutionStatus,
    FailureReason,
    PaymentStatus,
    PolicyOutcome,
    RiskLevel,
    WorkflowStage,
)
from app.schemas.common import Money


class ExpectedValueBreakdownRead(BaseModel):
    """Full expected-recovery-value arithmetic, in minor units (Requirement 10.2)."""

    recovery_probability: float
    payment_amount: int
    gross_expected_recovery: int
    intervention_cost: int
    customer_friction_penalty: int
    expected_recovery_value: int


class AlternativeRead(BaseModel):
    """A candidate that was evaluated but not selected (Requirement 12.2)."""

    action: ActionType
    probability: float
    expected_recovery_value: int


class DecisionExplanationRead(BaseModel):
    """Why this action was chosen (Requirement 12.1).

    Powers the later "why did the system choose this?" view.
    """

    selected_action: ActionType
    reason: str
    probability: float
    expected_recovery_value: int
    confidence: float
    alternatives: list[AlternativeRead] = Field(default_factory=list)


class DiagnosisRead(BaseModel):
    """Structured failure diagnosis (Requirement 7.1)."""

    failure_reason: FailureReason
    category: str
    transience: str
    requires_escalation: bool
    explanation: str


class PolicyResultRead(BaseModel):
    """The policy verdict and the rule that produced it (Requirement 13.1)."""

    outcome: PolicyOutcome
    rule_id: str
    reason: str


class RecoveryActionRead(BaseModel):
    """A proposed recovery action with its valuation and verdict."""

    model_config = ConfigDict(from_attributes=True)

    action_id: str
    action_type: ActionType
    estimated_probability: float
    confidence: float
    model_version: str
    expected_recovery_value: int
    erv_breakdown: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel
    policy_outcome: PolicyOutcome | None = None
    policy_rule_id: str | None = None
    policy_reason: str | None = None
    decision_explanation: dict[str, Any] = Field(default_factory=dict)
    status: ActionStatus
    requires_human_approval: bool = False
    created_at: datetime
    scheduled_at: datetime | None = None
    executed_at: datetime | None = None


class RecoveryOutcomeRead(BaseModel):
    """Independently verified result of an executed action (Requirement 15.1)."""

    model_config = ConfigDict(from_attributes=True)

    outcome_id: str
    action_id: str
    previous_payment_status: PaymentStatus
    new_payment_status: PaymentStatus
    recovered: bool
    recovered_amount: int
    failure_reason: FailureReason | None = None
    verification_timestamp: datetime


class RecoveryCaseSummary(BaseModel):
    """A recovery case in list form."""

    model_config = ConfigDict(from_attributes=True)

    case_id: str
    payment_id: str
    state: CaseState
    amount_at_risk: Money
    created_at: datetime
    updated_at: datetime
    gateway_order_id: str | None = None
    is_synthetic: bool = True
    failure_reason: str | None = None

    @classmethod
    def from_model(cls, case, currency: str = "INR") -> "RecoveryCaseSummary":
        gateway_order_id = None
        is_synthetic = True
        failure_reason = None
        payment = getattr(case, "payment", None)
        if payment is not None:
            is_synthetic = getattr(payment, "is_synthetic", True)
            fr = getattr(payment, "failure_reason", None)
            if fr is not None:
                failure_reason = fr.value if hasattr(fr, "value") else str(fr)
            gw = getattr(payment, "gateway_payment", None)
            if gw is not None:
                gateway_order_id = getattr(gw, "provider_order_id", None)
        elif case.diagnosis and isinstance(case.diagnosis, dict):
            failure_reason = case.diagnosis.get("failure_reason")

        return cls(
            case_id=case.case_id,
            payment_id=case.payment_id,
            state=case.state,
            amount_at_risk=Money.of(case.amount_at_risk, currency),
            created_at=case.created_at,
            updated_at=case.updated_at,
            gateway_order_id=gateway_order_id,
            is_synthetic=is_synthetic,
            failure_reason=failure_reason,
        )


class RecoveryCaseDetail(RecoveryCaseSummary):
    """A case with its diagnosis, actions, and latest decision explanation."""

    diagnosis: DiagnosisRead | None = None
    latest_action: RecoveryActionRead | None = None
    latest_explanation: DecisionExplanationRead | None = None
    latest_policy: PolicyResultRead | None = None
    latest_outcome: RecoveryOutcomeRead | None = None
    actions: list[RecoveryActionRead] = Field(default_factory=list)
    waiting_until: datetime | None = Field(
        default=None,
        description="Simulation time at which a scheduled action becomes due.",
    )
    is_terminal: bool = False


class ExecutionResultRead(BaseModel):
    """What the executor reported. Not proof of recovery (Requirement 15.2)."""

    action: ActionType
    status: ExecutionStatus
    provider_response: dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime


class WorkflowRunResponse(BaseModel):
    """The result of exactly one decide-policy-execute-verify cycle.

    One run performs at most one recovery action (Requirement 17.2, 17.8).
    """

    workflow_id: str
    case_id: str
    payment_id: str
    started_at: datetime
    ended_at: datetime
    state: CaseState
    final_status: CaseState
    selected_action: ActionType | None = None
    explanation: DecisionExplanationRead | None = None
    policy: PolicyResultRead | None = None
    execution: ExecutionResultRead | None = None
    outcome: RecoveryOutcomeRead | None = None
    recovered_amount: Money
    waiting_until: datetime | None = None
    stages: list[str] = Field(default_factory=list)
    message: str = ""


class AuditEventRead(BaseModel):
    """One audit trail entry (Requirement 19.2)."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    case_id: str
    payment_id: str
    stage: WorkflowStage
    event_type: AuditEventType
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime
    sequence: int = Field(
        default=0,
        description=(
            "Monotonic per-case ordering key. Several stages of one run share a "
            "simulation timestamp, so a timeline must order by this."
        ),
    )

    @classmethod
    def from_model(cls, event) -> "AuditEventRead":
        return cls(
            event_id=event.event_id,
            case_id=event.case_id,
            payment_id=event.payment_id,
            stage=event.stage,
            event_type=event.event_type,
            message=event.message,
            metadata=event.meta or {},
            timestamp=event.timestamp,
            sequence=event.sequence,
        )


class AuditTrailResponse(BaseModel):
    """A case's complete audit trail, oldest first (Requirement 19.7)."""

    case_id: str
    events: list[AuditEventRead]
    total: int
