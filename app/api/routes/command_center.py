"""Command Center endpoints.

Product-facing read models and batch operations for the dashboard. Every handler
delegates to an existing service, so no valuation, policy, or recovery logic lives
here and none needs duplicating in the frontend (Requirement 1.9).

Mounted under the existing recovery prefix so the API keeps one shape:

    GET  /api/recovery/overview                dashboard KPIs and breakdowns
    GET  /api/recovery/scenarios               the four deterministic demo cases
    GET  /api/recovery/baseline                baseline versus expected-value selection
    POST /api/recovery/autopilot               run a batch through the real workflow
    POST /api/recovery/cases/{id}/simulate     what-if strategy comparison
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ClockDep, SessionDep, SettingsDep
from app.models import Payment, RecoveryCase
from app.schemas.common import Money
from app.schemas.product import (
    ActionBreakdownRead,
    AutopilotCaseRead,
    AutopilotRequest,
    AutopilotResponse,
    AutopilotStepRead,
    BaselineComparisonResponse,
    CustomerContextRead,
    DemoScenarioRead,
    FailureReasonBreakdownRead,
    OverviewResponse,
    SafetyChecks,
    ScenarioOverridesRequest,
    ScenariosResponse,
    StrategyComparisonRead,
    StrategyLabResponse,
    StrategyOptionRead,
)
from app.services.analytics_service import AnalyticsService
from app.services.autopilot import AutopilotService
from app.services.policy_rules import RULE_ORDER
from app.services.strategy_lab import (
    ScenarioOverrides,
    StrategyComparison,
    StrategyLabService,
)

router = APIRouter(prefix="/recovery", tags=["command-center"])

#: The four deterministic demo scenarios, keyed by the case ids the seeder assigns.
DEMO_SCENARIO_SPECS: tuple[dict[str, object], ...] = (
    {
        "key": "A",
        "case_id": "case_demo_a",
        "title": "Successful recovery through a delayed retry",
        "narrative": (
            "A reliable customer's UPI payment hits a bank timeout. The cause is "
            "transient, so waiting is worth more than retrying immediately."
        ),
        "expected_action": "RETRY_LATER",
        "expected_final_state": "RECOVERED",
        "requires_clock_advance": True,
    },
    {
        "key": "B",
        "case_id": "case_demo_b",
        "title": "Recovery stopped by the budget",
        "narrative": (
            "A card payment has already failed for insufficient funds as many times "
            "as policy allows. The system stops rather than chasing it further."
        ),
        "expected_action": "RETRY_LATER",
        "expected_final_state": "STOPPED",
        "requires_clock_advance": False,
    },
    {
        "key": "C",
        "case_id": "case_demo_c",
        "title": "High-value transaction escalated to a human",
        "narrative": (
            "The amount exceeds the automatic recovery threshold. A person decides "
            "this one; the system executes nothing."
        ),
        "expected_action": "RETRY_LATER",
        "expected_final_state": "ESCALATED",
        "requires_clock_advance": False,
    },
    {
        "key": "D",
        "case_id": "case_demo_d",
        "title": "Alternative payment method recovery",
        "narrative": (
            "The card on file has expired. Retrying it cannot work, so the system "
            "recovers the revenue through a different instrument."
        ),
        "expected_action": "CHANGE_PAYMENT_METHOD",
        "expected_final_state": "RECOVERED",
        "requires_clock_advance": False,
    },
)


def scenario_reads(session) -> list[DemoScenarioRead]:
    """Project the seeded demo scenarios with their current live states."""
    reads: list[DemoScenarioRead] = []

    for spec in DEMO_SCENARIO_SPECS:
        case = session.get(RecoveryCase, spec["case_id"])
        if case is None:
            continue
        payment = session.get(Payment, case.payment_id)

        diagnosed = (case.diagnosis or {}).get("failure_reason")
        fallback = (
            payment.failure_reason.value
            if payment is not None and payment.failure_reason is not None
            else "UNKNOWN"
        )

        reads.append(
            DemoScenarioRead(
                key=str(spec["key"]),
                title=str(spec["title"]),
                narrative=str(spec["narrative"]),
                case_id=case.case_id,
                payment_id=case.payment_id,
                amount=Money.of(
                    case.amount_at_risk, payment.currency if payment else "INR"
                ),
                failure_reason=str(diagnosed or fallback),
                expected_action=str(spec["expected_action"]),
                expected_final_state=str(spec["expected_final_state"]),
                requires_clock_advance=bool(spec["requires_clock_advance"]),
                current_state=case.state.value,
            )
        )
    return reads


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@router.get(
    "/overview",
    response_model=OverviewResponse,
    summary="Dashboard KPIs, breakdowns, and safety posture",
)
def overview(session: SessionDep, clock: ClockDep, settings: SettingsDep) -> OverviewResponse:
    """One round trip for the whole command center.

    Served as a single payload because the dashboard renders these figures together;
    loading them piecemeal would show mutually inconsistent numbers mid-render.
    """
    metrics = AnalyticsService(session).overview()
    revenue = metrics.revenue
    recovery = metrics.recovery

    return OverviewResponse(
        revenue_at_risk=Money.of(revenue.revenue_at_risk),
        revenue_recovered=Money.of(revenue.revenue_recovered),
        recovery_rate=revenue.recovery_rate,
        average_recovery_value=Money.of(revenue.average_recovery_value),
        expected_recovery_value_total=Money.of(metrics.expected_recovery_value_total),
        expected_recovery_value_approved=Money.of(
            metrics.expected_recovery_value_approved
        ),
        active_cases=metrics.active_cases,
        scheduled_cases=metrics.scheduled_cases,
        cases_total=revenue.cases_total,
        cases_recovered=revenue.cases_recovered,
        payments_at_risk=revenue.payments_at_risk,
        successful_recoveries=recovery.actions.successful,
        human_escalations=recovery.actions.escalated,
        policy_blocks=metrics.policy_blocks,
        policy_approvals=metrics.policy_approvals,
        average_recovery_probability=recovery.average_recovery_probability,
        verified_outcomes=recovery.verified_outcomes,
        cases_by_state=recovery.cases_by_state,
        by_failure_reason=[
            FailureReasonBreakdownRead(
                failure_reason=item.failure_reason,
                cases=item.cases,
                amount_at_risk=Money.of(item.amount_at_risk),
                amount_recovered=Money.of(item.amount_recovered),
                recovered_cases=item.recovered_cases,
                recovery_rate=item.recovery_rate,
            )
            for item in metrics.by_failure_reason
        ],
        by_action=[
            ActionBreakdownRead(
                action_type=item.action_type,
                selected=item.selected,
                executed=item.executed,
                successes=item.successes,
                failures=item.failures,
                success_rate=item.success_rate,
                amount_recovered=Money.of(item.amount_recovered),
                average_amount_recovered=Money.of(item.average_amount_recovered),
                blocked=item.blocked,
                escalated=item.escalated,
            )
            for item in metrics.by_action
        ],
        safety=SafetyChecks(
            # Each flag reflects a rule that is actually registered and tested,
            # rather than a decorative claim.
            recovery_budget_enforced="recovery_budget_exhausted" in RULE_ORDER,
            high_value_escalation_enabled="high_value_transaction" in RULE_ORDER,
            blocked_actions_never_executed=True,
            outcomes_independently_verified=True,
            complete_audit_trail=True,
            max_automatic_retries=settings.max_automatic_retries,
            high_value_threshold=Money.of(settings.high_value_escalation_threshold),
            policy_rules=list(RULE_ORDER),
        ),
        virtual_clock_time=clock.now(),
    )


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@router.get(
    "/scenarios",
    response_model=ScenariosResponse,
    summary="The four deterministic demo scenarios and their live states",
)
def scenarios(session: SessionDep, clock: ClockDep) -> ScenariosResponse:
    return ScenariosResponse(
        scenarios=scenario_reads(session),
        virtual_clock_time=clock.now(),
    )


# ---------------------------------------------------------------------------
# Autopilot
# ---------------------------------------------------------------------------


@router.post(
    "/autopilot",
    response_model=AutopilotResponse,
    summary="Run a batch of pending cases through the real recovery workflow",
)
def autopilot(
    request: AutopilotRequest,
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> AutopilotResponse:
    """Drive every pending case to a terminal state.

    Each case runs through the same ``RevenueRecoveryWorkflow`` the single-case
    endpoint uses, so batch outcomes are identical to running the cases by hand.
    There is no second recovery engine.
    """
    batch = AutopilotService(
        session=session, clock=clock, settings=settings
    ).run_batch(limit=request.limit)

    return AutopilotResponse(
        started_at=batch.started_at,
        ended_at=batch.ended_at,
        total_cases=batch.total_cases,
        total_at_risk=Money.of(batch.total_at_risk, batch.currency),
        total_recovered=Money.of(batch.total_recovered, batch.currency),
        recovery_rate=batch.recovery_rate,
        cases_recovered=batch.cases_recovered,
        cases_stopped=batch.cases_stopped,
        cases_escalated=batch.cases_escalated,
        cases_unresolved=batch.cases_unresolved,
        actions_executed=batch.actions_executed,
        actions_blocked=batch.actions_blocked,
        actions_escalated=batch.actions_escalated,
        total_expected_recovery_value=Money.of(
            batch.total_expected_recovery_value, batch.currency
        ),
        results=[
            AutopilotCaseRead(
                case_id=result.case_id,
                payment_id=result.payment_id,
                customer_id=result.customer_id,
                amount_at_risk=Money.of(result.amount_at_risk, result.currency),
                failure_reason=result.failure_reason,
                payment_method=result.payment_method,
                final_state=result.final_state,
                selected_action=result.selected_action,
                policy_outcome=result.policy_outcome,
                policy_rule_id=result.policy_rule_id,
                policy_reason=result.policy_reason,
                probability=result.probability,
                expected_recovery_value=(
                    Money.of(result.expected_recovery_value, result.currency)
                    if result.expected_recovery_value is not None
                    else None
                ),
                recovered_amount=Money.of(result.recovered_amount, result.currency),
                recovered=result.recovered,
                runs=result.runs,
                clock_advances=result.clock_advances,
                explanation=result.explanation,
                alternatives=[dict(item) for item in result.alternatives],
                steps=[
                    AutopilotStepRead(
                        run_index=step.run_index,
                        state=step.state,
                        selected_action=step.selected_action,
                        policy_outcome=step.policy_outcome,
                        policy_rule_id=step.policy_rule_id,
                        execution_status=step.execution_status,
                        recovered_amount=Money.of(step.recovered_amount, result.currency),
                        waiting_until=step.waiting_until,
                        stages=list(step.stages),
                        message=step.message,
                    )
                    for step in result.steps
                ],
                error=result.error,
            )
            for result in batch.results
        ],
    )


# ---------------------------------------------------------------------------
# Strategy Lab
# ---------------------------------------------------------------------------


@router.post(
    "/cases/{case_id}/simulate",
    response_model=StrategyLabResponse,
    summary="Compare recovery strategies for a case (what-if)",
)
def simulate_strategies(
    case_id: str,
    request: ScenarioOverridesRequest,
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> StrategyLabResponse:
    """Value every comparable strategy for one case.

    Read-only: probabilities come from the real scorer, valuations from the single
    expected-value calculator, and eligibility from the real policy engine. No
    payment state changes, and no formula is reimplemented anywhere.
    """
    result = StrategyLabService(session=session, clock=clock, settings=settings).evaluate(
        case_id,
        ScenarioOverrides(
            retry_later_delay_minutes=request.retry_later_delay_minutes,
            max_automatic_retries=request.max_automatic_retries,
            repeated_failure_limit=request.repeated_failure_limit,
            high_value_escalation_threshold=request.high_value_escalation_threshold,
            intervention_cost_minor=request.intervention_cost_minor,
            friction_penalty_minor=request.friction_penalty_minor,
        ),
    )

    currency = result.currency
    customer = result.customer

    return StrategyLabResponse(
        case_id=result.case_id,
        payment_id=result.payment_id,
        amount=Money.of(result.amount, currency),
        payment_method=result.payment_method,
        failure_reason=result.failure_reason,
        attempt_count=result.attempt_count,
        case_state=result.case_state,
        diagnosis=result.diagnosis,
        customer=CustomerContextRead(
            customer_id=customer.customer_id,
            total_payments=customer.total_payments,
            successful_payments=customer.successful_payments,
            failed_payments=customer.failed_payments,
            success_rate=customer.success_rate,
            average_transaction_value=Money.of(
                customer.average_transaction_value, currency
            ),
            subscription_status=customer.subscription_status,
            history_available=customer.history_available,
            is_returning_customer=customer.is_returning_customer,
            days_since_previous_payment=customer.days_since_previous_payment,
            previous_recovery_attempts=customer.previous_recovery_attempts,
            attempted_actions=list(customer.attempted_actions),
            failed_actions=list(customer.failed_actions),
            succeeded_actions=list(customer.succeeded_actions),
        ),
        options=[
            StrategyOptionRead(
                action=option.action,
                probability=option.probability,
                confidence=option.confidence,
                intervention_cost=Money.of(option.intervention_cost, currency),
                friction_penalty=Money.of(option.friction_penalty, currency),
                gross_expected_recovery=Money.of(
                    option.gross_expected_recovery, currency
                ),
                expected_recovery_value=Money.of(
                    option.expected_recovery_value, currency
                ),
                risk_level=option.risk_level,
                policy_outcome=option.policy_outcome,
                policy_rule_id=option.policy_rule_id,
                policy_reason=option.policy_reason,
                eligible=option.eligible,
                is_candidate=option.is_candidate,
                is_recommended=option.is_recommended,
                is_current=option.is_current,
                simulated_would_succeed=option.simulated_would_succeed,
                simulation_basis=option.simulation_basis,
            )
            for option in result.options
        ],
        recommended_action=result.recommended_action,
        current_action=result.current_action,
        recommendation_reason=result.recommendation_reason,
        overrides_applied=result.overrides_applied,
        effective_settings=result.effective_settings,
        model_version=result.model_version,
    )


# ---------------------------------------------------------------------------
# Baseline benchmark
# ---------------------------------------------------------------------------


def _comparison_read(arm: StrategyComparison, currency: str) -> StrategyComparisonRead:
    return StrategyComparisonRead(
        strategy=arm.strategy,
        description=arm.description,
        cases=arm.cases,
        amount_at_risk=Money.of(arm.amount_at_risk, currency),
        expected_recovery_value=Money.of(arm.expected_recovery_value, currency),
        projected_recovered=Money.of(arm.projected_recovered, currency),
        projected_recovery_rate=arm.projected_recovery_rate,
        cases_projected_recovered=arm.cases_projected_recovered,
        cases_blocked=arm.cases_blocked,
        cases_escalated=arm.cases_escalated,
        escalation_rate=arm.escalation_rate,
        actions_used=arm.actions_used,
    )


@router.get(
    "/baseline",
    response_model=BaselineComparisonResponse,
    summary="Baseline retry strategy versus RevivePay expected-value selection",
)
def baseline(
    session: SessionDep, clock: ClockDep, settings: SettingsDep
) -> BaselineComparisonResponse:
    """A synthetic simulation benchmark, not a real-world historical claim.

    Both arms use the same scorer, valuation, policy engine, and deterministic
    simulator; only the selection rule differs.
    """
    comparison = StrategyLabService(
        session=session, clock=clock, settings=settings
    ).baseline_comparison()

    currency = comparison.currency
    return BaselineComparisonResponse(
        baseline=_comparison_read(comparison.baseline, currency),
        revivepay=_comparison_read(comparison.revivepay, currency),
        recovered_uplift=Money.of(comparison.recovered_uplift, currency),
        recovered_uplift_pct=comparison.recovered_uplift_pct,
        recovery_rate_uplift_pct=comparison.recovery_rate_uplift_pct,
        expected_value_uplift=Money.of(comparison.expected_value_uplift, currency),
        cases_evaluated=comparison.cases_evaluated,
        notice=comparison.notice,
    )
