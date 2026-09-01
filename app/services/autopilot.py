"""Autopilot: batch recovery across many cases.

This is orchestration *of* the orchestrator, not a second engine. Every case is
driven through the real ``RevenueRecoveryWorkflow``, so a batch produces exactly the
outcomes that running each case by hand would produce. Nothing here decides,
values, gates, executes, or verifies anything itself.

Two behaviours are worth calling out:

- **Delayed retries are driven to completion.** When a case schedules a
  ``RETRY_LATER``, autopilot advances the virtual clock and runs it again, so a
  batch finishes with cases in terminal states rather than parked. Without this the
  headline demo would end with everything "scheduled" and nothing recovered.
- **Cases are processed in a stable order** and every outcome derives from the
  seeded simulator, so a batch is reproducible run to run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings, get_settings
from app.core.enums import CaseState, PolicyOutcome
from app.core.errors import RevivePayError
from app.core.logging import get_logger
from app.models import Payment, RecoveryCase
from app.workflows.recovery_workflow import RevenueRecoveryWorkflow, WorkflowRun

logger = get_logger("autopilot")

#: Hard ceiling on runs per case, so a misconfiguration cannot spin forever.
MAX_RUNS_PER_CASE = 8


@dataclass(frozen=True)
class AutopilotStep:
    """One workflow run within a case's journey."""

    run_index: int
    state: CaseState
    selected_action: str | None
    policy_outcome: str | None
    policy_rule_id: str | None
    execution_status: str | None
    recovered_amount: int
    waiting_until: datetime | None
    stages: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class AutopilotCaseResult:
    """The complete journey of one case through the batch."""

    case_id: str
    payment_id: str
    amount_at_risk: int
    currency: str
    failure_reason: str
    payment_method: str
    customer_id: str
    final_state: CaseState
    selected_action: str | None
    policy_outcome: str | None
    policy_rule_id: str | None
    policy_reason: str | None
    probability: float | None
    expected_recovery_value: int | None
    recovered_amount: int
    runs: int
    clock_advances: int
    explanation: str | None
    alternatives: tuple[dict, ...]
    steps: tuple[AutopilotStep, ...]
    error: str | None = None

    @property
    def recovered(self) -> bool:
        return self.final_state is CaseState.RECOVERED


@dataclass(frozen=True)
class AutopilotBatchResult:
    """Batch totals, all derived from verified outcomes."""

    started_at: datetime
    ended_at: datetime
    clock_start: datetime
    clock_end: datetime
    total_cases: int
    total_at_risk: int
    total_recovered: int
    recovery_rate: float
    cases_recovered: int
    cases_stopped: int
    cases_escalated: int
    cases_unresolved: int
    actions_executed: int
    actions_blocked: int
    actions_escalated: int
    total_expected_recovery_value: int
    currency: str
    results: tuple[AutopilotCaseResult, ...] = field(default_factory=tuple)
    data_source: str = "synthetic_simulation"


class AutopilotService:
    """Runs a deterministic batch of at-risk cases to completion."""

    def __init__(
        self,
        session: Session,
        clock: VirtualClock,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._settings = settings or get_settings()

    # -- selection ---------------------------------------------------------

    def pending_cases(self, *, limit: int | None = None) -> list[RecoveryCase]:
        """Non-terminal cases in a stable order.

        Ordering by creation time then id keeps a batch reproducible; relying on
        insertion order would make the demo drift as the database grows.
        """
        statement = (
            select(RecoveryCase)
            .where(RecoveryCase.state.not_in(tuple(CaseState.terminal())))
            .order_by(RecoveryCase.created_at.asc(), RecoveryCase.case_id.asc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self._session.execute(statement).scalars().all())

    # -- execution ---------------------------------------------------------

    def run_batch(self, *, limit: int | None = None) -> AutopilotBatchResult:
        """Drive every pending case to a terminal state."""
        started_at = self._clock.now()
        cases = self.pending_cases(limit=limit)

        logger.info("autopilot | starting batch | cases=%s", len(cases))

        results = [self._run_case(case) for case in cases]
        ended_at = self._clock.now()

        return self._summarise(results, started_at, ended_at)

    def _run_case(self, case: RecoveryCase) -> AutopilotCaseResult:
        """Run one case until it terminates, advancing the clock when it waits."""
        payment = self._session.get(Payment, case.payment_id)
        workflow = RevenueRecoveryWorkflow(
            session=self._session, clock=self._clock, settings=self._settings
        )

        steps: list[AutopilotStep] = []
        last: WorkflowRun | None = None
        clock_advances = 0
        error: str | None = None

        # A scheduled resumption deliberately carries no policy verdict: the action
        # was gated on the run that scheduled it and is not re-gated. Reading only
        # the final run would therefore report "no policy decision" for every
        # successful delayed retry, so the decision and verdict are carried forward.
        decided: WorkflowRun | None = None
        gated: WorkflowRun | None = None

        for index in range(1, MAX_RUNS_PER_CASE + 1):
            self._session.refresh(case)
            if case.state in CaseState.terminal():
                break

            try:
                run = workflow.run(case.case_id)
            except RevivePayError as failure:
                error = failure.message
                logger.warning(
                    "autopilot | case=%s halted: %s", case.case_id, failure.message
                )
                break

            last = run
            if run.decision is not None:
                decided = run
            if run.policy is not None:
                gated = run

            steps.append(
                AutopilotStep(
                    run_index=index,
                    state=run.final_status,
                    selected_action=(
                        run.selected_action.value if run.selected_action else None
                    ),
                    policy_outcome=run.policy.outcome.value if run.policy else None,
                    policy_rule_id=run.policy.rule_id if run.policy else None,
                    execution_status=(
                        run.execution.status.value if run.execution else None
                    ),
                    recovered_amount=run.recovered_amount,
                    waiting_until=run.waiting_until,
                    stages=run.stages,
                    message=run.message,
                )
            )

            if run.final_status in CaseState.terminal():
                break

            # A scheduled retry only becomes due once simulation time moves.
            if run.waiting:
                self._clock.advance(minutes=self._settings.retry_later_delay_minutes)
                clock_advances += 1

        self._session.refresh(case)
        recovered = self._recovered_amount(case)

        return AutopilotCaseResult(
            case_id=case.case_id,
            payment_id=case.payment_id,
            amount_at_risk=int(case.amount_at_risk),
            currency=payment.currency if payment else self._settings.default_currency,
            failure_reason=self._failure_reason(case, payment),
            payment_method=payment.payment_method.value if payment else "UNKNOWN",
            customer_id=payment.customer_id if payment else "",
            final_state=case.state,
            selected_action=(
                (last.selected_action.value if last and last.selected_action else None)
                or (
                    decided.selected_action.value
                    if decided and decided.selected_action
                    else None
                )
            ),
            policy_outcome=gated.policy.outcome.value if gated and gated.policy else None,
            policy_rule_id=gated.policy.rule_id if gated and gated.policy else None,
            policy_reason=gated.policy.reason if gated and gated.policy else None,
            probability=decided.decision.probability if decided and decided.decision else None,
            expected_recovery_value=(
                decided.decision.expected_recovery_value
                if decided and decided.decision
                else None
            ),
            recovered_amount=recovered,
            runs=len(steps),
            clock_advances=clock_advances,
            explanation=(
                decided.decision.explanation.reason if decided and decided.decision else None
            ),
            alternatives=(
                tuple(dict(item) for item in decided.decision.explanation.alternatives)
                if decided and decided.decision
                else ()
            ),
            steps=tuple(steps),
            error=error,
        )

    # -- summary -----------------------------------------------------------

    def _summarise(
        self,
        results: list[AutopilotCaseResult],
        started_at: datetime,
        ended_at: datetime,
    ) -> AutopilotBatchResult:
        total_at_risk = sum(result.amount_at_risk for result in results)
        total_recovered = sum(result.recovered_amount for result in results)

        def count_state(state: CaseState) -> int:
            return sum(1 for result in results if result.final_state is state)

        actions_executed = sum(
            1
            for result in results
            for step in result.steps
            if step.execution_status in {"SUCCEEDED", "FAILED"}
        )
        actions_blocked = sum(
            1
            for result in results
            for step in result.steps
            if step.policy_outcome == PolicyOutcome.BLOCKED.value
        )
        actions_escalated = sum(
            1
            for result in results
            for step in result.steps
            if step.policy_outcome == PolicyOutcome.ESCALATED.value
        )

        unresolved = sum(
            1 for result in results if result.final_state not in CaseState.terminal()
        )

        logger.info(
            "autopilot | batch complete | cases=%s recovered=%s at_risk=%s",
            len(results),
            total_recovered,
            total_at_risk,
        )

        return AutopilotBatchResult(
            started_at=started_at,
            ended_at=ended_at,
            clock_start=started_at,
            clock_end=ended_at,
            total_cases=len(results),
            total_at_risk=total_at_risk,
            total_recovered=total_recovered,
            recovery_rate=(
                round(total_recovered / total_at_risk, 4) if total_at_risk else 0.0
            ),
            cases_recovered=count_state(CaseState.RECOVERED),
            cases_stopped=count_state(CaseState.STOPPED),
            cases_escalated=count_state(CaseState.ESCALATED),
            cases_unresolved=unresolved,
            actions_executed=actions_executed,
            actions_blocked=actions_blocked,
            actions_escalated=actions_escalated,
            total_expected_recovery_value=sum(
                result.expected_recovery_value or 0 for result in results
            ),
            currency=self._settings.default_currency,
            results=tuple(results),
        )

    # -- helpers -----------------------------------------------------------

    def _recovered_amount(self, case: RecoveryCase) -> int:
        """Verified recovered amount for a case (Requirement 15.7)."""
        return sum(
            action.outcome.recovered_amount
            for action in case.actions
            if action.outcome is not None and action.outcome.recovered
        )

    @staticmethod
    def _failure_reason(case: RecoveryCase, payment: Payment | None) -> str:
        diagnosis = case.diagnosis or {}
        reason = diagnosis.get("failure_reason")
        if reason:
            return str(reason)
        if payment is not None and payment.failure_reason is not None:
            return payment.failure_reason.value
        return "UNKNOWN"


__all__ = [
    "MAX_RUNS_PER_CASE",
    "AutopilotBatchResult",
    "AutopilotCaseResult",
    "AutopilotService",
    "AutopilotStep",
]
