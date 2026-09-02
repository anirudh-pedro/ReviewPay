"""Command Center schemas.

Response shapes for the product surfaces: dashboard overview, autopilot batches,
Strategy Lab what-if comparisons, the baseline benchmark, and demo control.

Conventions carried over from the existing schemas: money is an integer in minor
units paired with a currency code, and every computed payload carries the synthetic
data marker (Requirement 20.5, 24.7).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.core.enums import CaseState
from app.schemas.common import Money, SyntheticNotice


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


class FailureReasonBreakdownRead(BaseModel):
    """Recovery performance for one failure cause."""

    failure_reason: str
    cases: int
    amount_at_risk: Money
    amount_recovered: Money
    recovered_cases: int
    recovery_rate: float


class ActionBreakdownRead(BaseModel):
    """Recovery performance for one action type.

    ``selected`` minus ``executed`` is what policy refused to run.
    """

    action_type: str
    selected: int
    executed: int
    successes: int
    failures: int
    success_rate: float
    amount_recovered: Money
    average_amount_recovered: Money
    blocked: int
    escalated: int


class SafetyChecks(BaseModel):
    """Evidence that automation is bounded, not blind."""

    recovery_budget_enforced: bool
    high_value_escalation_enabled: bool
    blocked_actions_never_executed: bool
    outcomes_independently_verified: bool
    complete_audit_trail: bool
    max_automatic_retries: int
    high_value_threshold: Money
    policy_rules: list[str]


class OverviewResponse(SyntheticNotice):
    """Everything the dashboard needs in one round trip."""

    revenue_at_risk: Money
    revenue_recovered: Money
    recovery_rate: float
    average_recovery_value: Money
    expected_recovery_value_total: Money
    expected_recovery_value_approved: Money

    active_cases: int
    scheduled_cases: int
    cases_total: int
    cases_recovered: int
    payments_at_risk: int

    successful_recoveries: int
    human_escalations: int
    policy_blocks: int
    policy_approvals: int

    average_recovery_probability: float
    verified_outcomes: int
    cases_by_state: dict[str, int]

    by_failure_reason: list[FailureReasonBreakdownRead]
    by_action: list[ActionBreakdownRead]

    safety: SafetyChecks
    virtual_clock_time: datetime


# ---------------------------------------------------------------------------
# Autopilot
# ---------------------------------------------------------------------------


class AutopilotRequest(BaseModel):
    """Run a deterministic batch of pending recovery cases."""

    limit: int | None = Field(
        default=None,
        ge=1,
        le=200,
        description="Maximum cases to process. Omit to process every pending case.",
    )


class AutopilotStepRead(BaseModel):
    """One workflow run within a case's journey."""

    run_index: int
    state: CaseState
    selected_action: str | None = None
    policy_outcome: str | None = None
    policy_rule_id: str | None = None
    execution_status: str | None = None
    recovered_amount: Money
    waiting_until: datetime | None = None
    stages: list[str] = Field(default_factory=list)
    message: str = ""


class AutopilotCaseRead(BaseModel):
    """The complete journey of one case."""

    case_id: str
    payment_id: str
    customer_id: str
    amount_at_risk: Money
    failure_reason: str
    payment_method: str
    final_state: CaseState
    selected_action: str | None = None
    policy_outcome: str | None = None
    policy_rule_id: str | None = None
    policy_reason: str | None = None
    probability: float | None = None
    expected_recovery_value: Money | None = None
    recovered_amount: Money
    recovered: bool
    runs: int
    clock_advances: int
    explanation: str | None = None
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[AutopilotStepRead] = Field(default_factory=list)
    error: str | None = None


class AutopilotResponse(SyntheticNotice):
    """Batch totals plus the per-case detail behind them."""

    started_at: datetime
    ended_at: datetime
    total_cases: int
    total_at_risk: Money
    total_recovered: Money
    recovery_rate: float
    cases_recovered: int
    cases_stopped: int
    cases_escalated: int
    cases_unresolved: int
    actions_executed: int
    actions_blocked: int
    actions_escalated: int
    total_expected_recovery_value: Money
    results: list[AutopilotCaseRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Strategy Lab
# ---------------------------------------------------------------------------


class ScenarioOverridesRequest(BaseModel):
    """Optional parameter adjustments for a what-if run.

    Each field maps onto a real setting, so the backend remains the single source of
    truth for both valuation and policy.
    """

    retry_later_delay_minutes: int | None = Field(default=None, ge=0, le=10_080)
    max_automatic_retries: int | None = Field(default=None, ge=0, le=20)
    repeated_failure_limit: int | None = Field(default=None, ge=0, le=20)
    high_value_escalation_threshold: int | None = Field(
        default=None, ge=0, description="Minor units."
    )
    intervention_cost_minor: dict[str, int] | None = Field(
        default=None, description="Per-action override, minor units."
    )
    friction_penalty_minor: dict[str, int] | None = Field(
        default=None, description="Per-action override, minor units."
    )

    @model_validator(mode="after")
    def _reject_negative_costs(self) -> "ScenarioOverridesRequest":
        for label, mapping in (
            ("intervention_cost_minor", self.intervention_cost_minor),
            ("friction_penalty_minor", self.friction_penalty_minor),
        ):
            for action, value in (mapping or {}).items():
                if value < 0:
                    raise ValueError(f"{label}[{action}] must not be negative")
        return self


class StrategyOptionRead(BaseModel):
    """One candidate strategy, valued and policy-checked by the backend."""

    action: str
    probability: float
    confidence: float
    intervention_cost: Money
    friction_penalty: Money
    gross_expected_recovery: Money
    expected_recovery_value: Money
    risk_level: str
    policy_outcome: str
    policy_rule_id: str
    policy_reason: str
    eligible: bool
    is_candidate: bool
    is_recommended: bool
    is_current: bool
    simulated_would_succeed: bool
    simulation_basis: str


class CustomerContextRead(BaseModel):
    """Behavioural context shown beside the strategies."""

    customer_id: str
    total_payments: int
    successful_payments: int
    failed_payments: int
    success_rate: float
    average_transaction_value: Money
    subscription_status: str
    history_available: bool
    is_returning_customer: bool
    days_since_previous_payment: int | None = None
    previous_recovery_attempts: int
    attempted_actions: list[str] = Field(default_factory=list)
    failed_actions: list[str] = Field(default_factory=list)
    succeeded_actions: list[str] = Field(default_factory=list)


class StrategyLabResponse(SyntheticNotice):
    """A complete what-if comparison for one case."""

    case_id: str
    payment_id: str
    amount: Money
    payment_method: str
    failure_reason: str
    attempt_count: int
    case_state: str
    diagnosis: dict[str, Any]
    customer: CustomerContextRead
    options: list[StrategyOptionRead]
    recommended_action: str | None = None
    current_action: str | None = None
    recommendation_reason: str
    overrides_applied: bool
    effective_settings: dict[str, Any]
    model_version: str


# ---------------------------------------------------------------------------
# Baseline benchmark
# ---------------------------------------------------------------------------


class StrategyComparisonRead(BaseModel):
    """One arm of the benchmark."""

    strategy: str
    description: str
    cases: int
    amount_at_risk: Money
    expected_recovery_value: Money
    projected_recovered: Money
    projected_recovery_rate: float
    cases_projected_recovered: int
    cases_blocked: int
    cases_escalated: int
    escalation_rate: float
    actions_used: dict[str, int]


class BaselineComparisonResponse(SyntheticNotice):
    """Measurable impact of expected-value selection over blind retrying."""

    baseline: StrategyComparisonRead
    revivepay: StrategyComparisonRead
    recovered_uplift: Money
    recovered_uplift_pct: float
    recovery_rate_uplift_pct: float
    expected_value_uplift: Money
    cases_evaluated: int


# ---------------------------------------------------------------------------
# Scenarios and demo control
# ---------------------------------------------------------------------------


class DemoScenarioRead(BaseModel):
    """One of the deterministic demonstration cases."""

    key: str
    title: str
    narrative: str
    case_id: str
    payment_id: str
    amount: Money
    failure_reason: str
    expected_action: str
    expected_final_state: str
    requires_clock_advance: bool
    current_state: str


class ScenariosResponse(SyntheticNotice):
    """The seeded demo scenarios and their current states."""

    scenarios: list[DemoScenarioRead]
    virtual_clock_time: datetime


class DemoResetRequest(BaseModel):
    """Reseed the deterministic demo data."""

    background_customers: int = Field(default=12, ge=0, le=60)


class DemoResetResponse(SyntheticNotice):
    """What the reset produced."""

    customers: int
    payments: int
    cases: int
    scenarios: list[DemoScenarioRead]
    virtual_clock_time: datetime
    message: str


# ---------------------------------------------------------------------------
# Judge Demo Flow
# ---------------------------------------------------------------------------


class JudgeDemoStageRead(BaseModel):
    """One of the 8 proof stages in the Judge Demo pipeline."""

    stage_number: int
    name: str
    label: str
    status: str
    detail: str
    payload: dict[str, Any]


class JudgeDemoResponse(SyntheticNotice):
    """Complete 8-stage proof payload for Judge Demo evaluation."""

    case_id: str
    payment_id: str
    amount: Money
    evidence_source: str
    is_real_razorpay: bool
    razorpay_order_id: str | None
    razorpay_payment_id: str | None

    ai_root_cause: str
    ai_confidence: float
    ai_recommended_action: str
    ai_reasoning: str

    selected_action: str | None
    expected_recovery_value: Money | None
    gross_recovery: Money | None
    intervention_cost: Money | None
    friction_penalty: Money | None

    policy_outcome: str | None
    policy_rule_id: str | None
    policy_reason: str | None

    final_case_state: str
    execution_status: str | None
    recovered_amount: Money
    is_recovered: bool

    stages: list[JudgeDemoStageRead]

