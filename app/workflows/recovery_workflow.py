"""Revenue recovery workflow: the orchestration boundary.

The only component that knows the pipeline order (Requirement 17.3). Every other
component knows its own inputs and outputs and nothing about its neighbours, which
is what lets any one of them be replaced in a later phase.

One call performs **exactly one** decide -> policy -> execute -> verify cycle
(Requirement 17.2). A case that is neither recovered nor blocked returns to a
re-runnable state and the next run re-decides with the updated attempt count and
recovery history, so progress is inspectable step by step rather than hidden inside
a loop.

Three invariants are enforced here and visible in one screen:

1. Execution is reachable only after the policy engine returns ``APPROVED``.
2. ``RETRY_LATER`` schedules and stops; it charges nothing until the virtual clock
   reaches the due time and a later run picks it up.
3. Recovery is confirmed by re-reading payment state, never by trusting the
   executor's own report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    WorkflowStage,
)
from app.core.errors import CaseAlreadyTerminal, RecordNotFound, RevivePayError
from app.core.logging import get_logger, log_context
from app.db.base import new_id
from app.integrations.action_executor import ExecutionResult
from app.models import Payment, RecoveryAction, RecoveryCase, RecoveryOutcome
from app.services.audit_service import AuditService
from app.services.candidate_generator import RecoveryActionCandidateGenerator
from app.services.context_builder import RecoveryContext, RecoveryContextBuilder
from app.services.decision_engine import RecoveryDecision, RecoveryDecisionEngine
from app.services.diagnosis_engine import Diagnosis, DiagnosisEngine
from app.services.expected_value import ExpectedRecoveryCalculator
from app.services.outcome_verifier import OutcomeVerifier
from app.services.policy_engine import PolicyEngine
from app.services.policy_rules import PolicyResult
from app.services.state_machine import StateMachine

logger = get_logger("workflow")

#: States from which a run may begin.
RUNNABLE_STATES = frozenset({CaseState.DETECTED, CaseState.FAILED, CaseState.SCHEDULED})


class CaseNotRunnable(RevivePayError):
    """The case is mid-flight in an intermediate state and cannot be run."""

    code = "CASE_NOT_RUNNABLE"
    http_status = 409

    def __init__(self, case_id: str, state: CaseState) -> None:
        super().__init__(
            f"Recovery case '{case_id}' is in state {state.value}, which is not a runnable "
            f"state. Runnable states are: "
            f"{', '.join(sorted(item.value for item in RUNNABLE_STATES))}."
        )
        self.case_id = case_id
        self.state = state


@dataclass(frozen=True)
class WorkflowRun:
    """Everything that happened in one run (Requirement 23.1)."""

    workflow_id: str
    case_id: str
    payment_id: str
    started_at: datetime
    ended_at: datetime
    state: CaseState
    final_status: CaseState
    recovered_amount: int
    currency: str = "INR"
    selected_action: ActionType | None = None
    decision: RecoveryDecision | None = None
    policy: PolicyResult | None = None
    execution: ExecutionResult | None = None
    outcome: RecoveryOutcome | None = None
    action_id: str | None = None
    waiting_until: datetime | None = None
    stages: tuple[str, ...] = ()
    message: str = ""

    @property
    def recovered(self) -> bool:
        return self.final_status is CaseState.RECOVERED

    @property
    def waiting(self) -> bool:
        return self.waiting_until is not None

    def to_log_line(self) -> str:
        """One-line summary for a live demo."""
        return (
            f"[{self.workflow_id}] case={self.case_id} payment={self.payment_id} "
            f"action={self.selected_action.value if self.selected_action else '-'} "
            f"policy={self.policy.outcome.value if self.policy else '-'} "
            f"final={self.final_status.value} recovered={self.recovered_amount}"
        )


@dataclass
class _RunState:
    """Mutable bookkeeping for one run. Not part of the public contract."""

    workflow_id: str
    started_at: datetime
    stages: list[str] = field(default_factory=list)

    def stage(self, name: str) -> None:
        self.stages.append(name)


class RevenueRecoveryWorkflow:
    """Sequences one recovery cycle for one at-risk payment."""

    def __init__(
        self,
        session: Session,
        clock: VirtualClock,
        *,
        settings: Settings | None = None,
        diagnosis_engine: DiagnosisEngine | None = None,
        predictor: Any | None = None,
        executor: Any | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._settings = settings or get_settings()

        from app.core.container import (
            get_action_executor,
            get_diagnosis_engine,
            get_recovery_predictor,
        )

        self._diagnosis = diagnosis_engine or get_diagnosis_engine(self._settings)
        self._predictor = predictor or get_recovery_predictor(self._settings)
        self._executor = executor or get_action_executor(session, self._settings, clock)

        self._context_builder = RecoveryContextBuilder(session, clock)
        self._candidates = RecoveryActionCandidateGenerator()
        self._calculator = ExpectedRecoveryCalculator(self._settings)
        self._decision_engine = RecoveryDecisionEngine(
            predictor=self._predictor,
            calculator=self._calculator,
            settings=self._settings,
        )
        self._policy = PolicyEngine(
            settings=self._settings,
            supported_actions=self._executor.supported_actions,
        )
        self._verifier = OutcomeVerifier(session, clock)
        self._audit = AuditService(session, clock)
        self._states = StateMachine(clock)

    # -- entry point -------------------------------------------------------

    def run(self, case_id: str) -> WorkflowRun:
        """Perform one recovery cycle (Requirement 17.1)."""
        case = self._session.get(RecoveryCase, case_id)
        if case is None:
            raise RecordNotFound("RecoveryCase", case_id)

        if case.is_terminal:
            raise CaseAlreadyTerminal(case_id, case.state)

        if case.state not in RUNNABLE_STATES:
            raise CaseNotRunnable(case_id, case.state)

        run = _RunState(workflow_id=new_id("wf"), started_at=self._clock.now())
        entry_state = case.state

        # The context reaches every structured log produced by the downstream
        # workflow stages without coupling domain services to FastAPI.
        with log_context(workflow_id=run.workflow_id):
            logger.info(
                "[%s] run start | case=%s | state=%s | simulation_time=%s",
                run.workflow_id,
                case.case_id,
                entry_state.value,
                run.started_at.isoformat(),
            )

            try:
                if entry_state is CaseState.SCHEDULED:
                    result = self._resume_scheduled(case, run)
                else:
                    result = self._full_cycle(case, run)
            except (CaseAlreadyTerminal, CaseNotRunnable, RecordNotFound):
                raise
            except Exception as error:  # noqa: BLE001 - deliberate boundary
                self._handle_stage_error(case, run, entry_state, error)
                raise

            self._session.commit()
            logger.info("%s", result.to_log_line())
            return result

    # -- scheduled resumption ---------------------------------------------

    def _resume_scheduled(self, case: RecoveryCase, run: _RunState) -> WorkflowRun:
        """Execute a previously approved action whose due time has arrived.

        No re-decision and no second policy check: the action was decided and
        approved on the run that scheduled it. Re-deciding here would let a case
        drift from what a reviewer saw approved.
        """
        action = self._pending_scheduled_action(case.case_id)
        if action is None:
            # Nothing pending; treat as a fresh cycle rather than stalling.
            self._states.transition(case, CaseState.EXECUTING)
            self._states.transition(case, CaseState.VERIFYING)
            self._states.transition(case, CaseState.FAILED)
            return self._finish(
                case,
                run,
                final_status=CaseState.FAILED,
                message="No pending scheduled action was found; case returned for re-decision.",
            )

        run.stage("scheduling_check")

        if not self._clock.is_due(action.scheduled_at):
            # Requirement 18.5: report the wait, execute nothing.
            logger.info(
                "[%s] waiting | case=%s | %s due at %s | now %s",
                run.workflow_id,
                case.case_id,
                action.action_type.value,
                action.scheduled_at.isoformat(),
                self._clock.now().isoformat(),
            )
            return self._finish(
                case,
                run,
                final_status=case.state,
                selected_action=action.action_type,
                action_id=action.action_id,
                waiting_until=action.scheduled_at,
                message=(
                    f"{action.action_type.value} is scheduled for "
                    f"{action.scheduled_at.isoformat()}; simulation time is "
                    f"{self._clock.now().isoformat()}. Advance the clock to make it due."
                ),
            )

        context = self._context_builder.build(case)
        return self._execute_and_verify(case, run, action, context, policy=None)

    def _pending_scheduled_action(self, case_id: str) -> RecoveryAction | None:
        statement = (
            select(RecoveryAction)
            .where(RecoveryAction.case_id == case_id)
            .where(RecoveryAction.scheduled_at.is_not(None))
            .where(RecoveryAction.executed_at.is_(None))
            .order_by(RecoveryAction.scheduled_at.asc(), RecoveryAction.action_id.asc())
        )
        return self._session.execute(statement).scalars().first()

    # -- full cycle --------------------------------------------------------

    def _full_cycle(self, case: RecoveryCase, run: _RunState) -> WorkflowRun:
        """Diagnose, decide, gate, then act."""
        # --- diagnosis ---
        self._states.transition(case, CaseState.DIAGNOSING)
        context = self._context_builder.build(case)
        run.stage("context")

        diagnosis = self._diagnosis.diagnose(context)
        case.diagnosis = diagnosis.to_dict()
        self._audit_diagnosis(case, context, diagnosis, run)
        self._states.transition(case, CaseState.DIAGNOSED)
        run.stage("diagnosis")
        logger.info(
            "[%s] diagnosis | %s | %s / %s",
            run.workflow_id,
            context.payment_id,
            diagnosis.failure_reason.value,
            diagnosis.transience.value,
        )

        # Rebuild so the decision path sees the persisted diagnosis.
        context = self._context_builder.build(case)

        # --- decision ---
        self._states.transition(case, CaseState.EVALUATING)
        candidates = self._candidates.generate(context, diagnosis)
        run.stage("candidates")

        decision = self._decision_engine.decide(
            context, diagnosis, candidates, audit=self._audit, workflow_id=run.workflow_id
        )
        run.stage("decision")

        action = self._persist_action(case, context, decision)
        self._states.transition(case, CaseState.DECISION_READY)

        # --- policy gate (Requirement 13.9) ---
        self._states.transition(case, CaseState.POLICY_CHECK)
        policy = self._policy.evaluate(context, decision)
        self._policy.apply_to_action(action, policy)
        self._policy.audit(self._audit, context, decision, policy, run.workflow_id)
        run.stage("policy")

        if policy.outcome is PolicyOutcome.BLOCKED:
            return self._stop(case, run, action, context, decision, policy)

        if policy.outcome is PolicyOutcome.ESCALATED:
            return self._escalate(case, run, action, context, decision, policy)

        # --- approved dispositions that move no money ---
        if decision.selected_action is ActionType.ESCALATE_HUMAN:
            execution = self._executor.execute(
                decision.selected_action, context, audit=self._audit, workflow_id=run.workflow_id
            )
            return self._escalate(case, run, action, context, decision, policy, execution)

        if decision.selected_action is ActionType.STOP:
            execution = self._executor.execute(
                decision.selected_action, context, audit=self._audit, workflow_id=run.workflow_id
            )
            return self._stop(case, run, action, context, decision, policy, execution)

        # --- approved ---
        self._states.transition(case, CaseState.APPROVED)

        if decision.selected_action is ActionType.RETRY_LATER:
            return self._schedule(case, run, action, context, decision, policy)

        return self._execute_and_verify(case, run, action, context, policy=policy, decision=decision)

    # -- dispositions ------------------------------------------------------

    def _schedule(
        self,
        case: RecoveryCase,
        run: _RunState,
        action: RecoveryAction,
        context: RecoveryContext,
        decision: RecoveryDecision,
        policy: PolicyResult,
    ) -> WorkflowRun:
        """Defer a delayed retry (Requirement 18.3)."""
        due = self._clock.now() + timedelta(minutes=self._settings.retry_later_delay_minutes)

        execution = self._executor.schedule(decision.selected_action, context, due)

        action.scheduled_at = due
        action.status = ActionStatus.SCHEDULED
        self._states.transition(case, CaseState.SCHEDULED)
        run.stage("scheduled")

        self._audit.record(
            case_id=case.case_id,
            payment_id=case.payment_id,
            stage=WorkflowStage.SCHEDULING,
            event_type=AuditEventType.ACTION_SCHEDULED,
            message=(
                f"{decision.selected_action.value} scheduled for {due.isoformat()} "
                f"({self._settings.retry_later_delay_minutes} minutes after "
                f"{self._clock.now().isoformat()}). No charge attempted."
            ),
            metadata={
                "action_id": action.action_id,
                "action": decision.selected_action.value,
                "scheduled_at": due.isoformat(),
                "scheduled_from": self._clock.now().isoformat(),
                "delay_minutes": self._settings.retry_later_delay_minutes,
                "expected_recovery_value": decision.expected_recovery_value,
                "provider_response": execution.provider_response,
            },
            workflow_id=run.workflow_id,
        )

        logger.info(
            "[%s] scheduled | case=%s | %s due %s",
            run.workflow_id,
            case.case_id,
            decision.selected_action.value,
            due.isoformat(),
        )

        return self._finish(
            case,
            run,
            final_status=CaseState.SCHEDULED,
            selected_action=decision.selected_action,
            decision=decision,
            policy=policy,
            execution=execution,
            action_id=action.action_id,
            waiting_until=due,
            message=(
                f"{decision.selected_action.value} scheduled for {due.isoformat()}. "
                "Advance the simulation clock, then run the case again to execute it."
            ),
        )

    def _execute_and_verify(
        self,
        case: RecoveryCase,
        run: _RunState,
        action: RecoveryAction,
        context: RecoveryContext,
        *,
        policy: PolicyResult | None,
        decision: RecoveryDecision | None = None,
    ) -> WorkflowRun:
        """Execute, then verify independently (Requirement 15.2)."""
        payment = self._session.get(Payment, case.payment_id)
        if payment is None:
            raise RecordNotFound("Payment", case.payment_id)

        # Captured before execution so the transition can be described afterwards.
        previous_status: PaymentStatus = payment.status

        if case.state is not CaseState.EXECUTING:
            self._states.transition(case, CaseState.EXECUTING)

        execution = self._executor.execute(
            action.action_type, context, audit=self._audit, workflow_id=run.workflow_id
        )
        action.executed_at = execution.executed_at
        action.status = (
            ActionStatus.EXECUTED
            if execution.reported_success
            else ActionStatus.FAILED
        )
        run.stage("execution")

        self._states.transition(case, CaseState.VERIFYING)
        outcome = self._verifier.verify(
            action, previous_status, audit=self._audit, workflow_id=run.workflow_id
        )
        run.stage("verification")

        final = CaseState.RECOVERED if outcome.recovered else CaseState.FAILED
        self._states.transition(case, final)

        if outcome.recovered:
            case.terminal_outcome = {
                "recovered": True,
                "recovered_amount": outcome.recovered_amount,
                "action": action.action_type.value,
                "verified_at": outcome.verification_timestamp.isoformat(),
            }

        logger.info(
            "[%s] %s | case=%s | recovered=%s amount=%s",
            run.workflow_id,
            final.value,
            case.case_id,
            outcome.recovered,
            outcome.recovered_amount,
        )

        return self._finish(
            case,
            run,
            final_status=final,
            selected_action=action.action_type,
            decision=decision,
            policy=policy,
            execution=execution,
            outcome=outcome,
            action_id=action.action_id,
            recovered_amount=outcome.recovered_amount,
            message=(
                f"Recovered {outcome.recovered_amount} {payment.currency} minor units via "
                f"{action.action_type.value}."
                if outcome.recovered
                else (
                    f"{action.action_type.value} did not recover the payment; the case is "
                    "available for another run."
                )
            ),
        )

    def _stop(
        self,
        case: RecoveryCase,
        run: _RunState,
        action: RecoveryAction,
        context: RecoveryContext,
        decision: RecoveryDecision,
        policy: PolicyResult,
        execution: ExecutionResult | None = None,
    ) -> WorkflowRun:
        """Terminate the case (Requirement 17.6)."""
        self._states.transition(case, CaseState.BLOCKED)
        self._states.transition(case, CaseState.STOPPED)
        run.stage("stopped")

        case.terminal_outcome = {
            "recovered": False,
            "stopped_by_rule": policy.rule_id,
            "reason": policy.reason,
        }

        self._audit.record(
            case_id=case.case_id,
            payment_id=case.payment_id,
            stage=WorkflowStage.COMPLETION,
            event_type=AuditEventType.WORKFLOW_STOPPED,
            message=f"Workflow stopped: {policy.reason}",
            metadata={
                "policy_rule_id": policy.rule_id,
                "policy_reason": policy.reason,
                "evaluated_action": decision.selected_action.value,
                "attempt_count": context.attempt_count,
                "unsuccessful_outcome_count": context.unsuccessful_outcome_count,
                "amount_at_risk": case.amount_at_risk,
            },
            workflow_id=run.workflow_id,
        )

        logger.info(
            "[%s] stopped | case=%s | rule=%s", run.workflow_id, case.case_id, policy.rule_id
        )

        return self._finish(
            case,
            run,
            final_status=CaseState.STOPPED,
            selected_action=decision.selected_action,
            decision=decision,
            policy=policy,
            execution=execution,
            action_id=action.action_id,
            message=f"Recovery stopped by policy rule '{policy.rule_id}': {policy.reason}",
        )

    def _escalate(
        self,
        case: RecoveryCase,
        run: _RunState,
        action: RecoveryAction,
        context: RecoveryContext,
        decision: RecoveryDecision,
        policy: PolicyResult,
        execution: ExecutionResult | None = None,
    ) -> WorkflowRun:
        """Hand the case to a human (Requirement 17.7). Nothing is charged."""
        self._states.transition(case, CaseState.ESCALATED)
        run.stage("escalated")

        case.terminal_outcome = {
            "recovered": False,
            "escalated_by_rule": policy.rule_id,
            "reason": policy.reason,
        }

        logger.info(
            "[%s] escalated | case=%s | rule=%s", run.workflow_id, case.case_id, policy.rule_id
        )

        return self._finish(
            case,
            run,
            final_status=CaseState.ESCALATED,
            selected_action=decision.selected_action,
            decision=decision,
            policy=policy,
            execution=execution,
            action_id=action.action_id,
            message=f"Escalated for human review by rule '{policy.rule_id}': {policy.reason}",
        )

    # -- helpers -----------------------------------------------------------

    def _persist_action(
        self, case: RecoveryCase, context: RecoveryContext, decision: RecoveryDecision
    ) -> RecoveryAction:
        """Record the proposed action with its valuation and explanation."""
        action = RecoveryAction(
            action_id=new_id("act"),
            case_id=case.case_id,
            payment_id=case.payment_id,
            action_type=decision.selected_action,
            estimated_probability=decision.probability,
            confidence=decision.confidence,
            model_version=decision.model_version,
            expected_recovery_value=decision.expected_recovery_value,
            erv_breakdown=decision.breakdown.to_dict(),
            risk_level=decision.risk_level,
            decision_explanation=decision.explanation.to_dict(),
            status=ActionStatus.PROPOSED,
            created_at=self._clock.now(),
        )
        self._session.add(action)
        self._session.flush()
        return action

    def _audit_diagnosis(
        self,
        case: RecoveryCase,
        context: RecoveryContext,
        diagnosis: Diagnosis,
        run: _RunState,
    ) -> None:
        self._audit.record(
            case_id=case.case_id,
            payment_id=case.payment_id,
            stage=WorkflowStage.DIAGNOSIS,
            event_type=AuditEventType.DIAGNOSIS_COMPLETED,
            message=diagnosis.explanation,
            metadata={
                "failure_reason": diagnosis.failure_reason.value,
                "category": diagnosis.category.value,
                "transience": diagnosis.transience.value,
                "requires_escalation": diagnosis.requires_escalation,
                "attempt_count": context.attempt_count,
                "previous_recovery_attempts": context.previous_recovery_attempt_count,
            },
            workflow_id=run.workflow_id,
        )

    def _finish(
        self,
        case: RecoveryCase,
        run: _RunState,
        *,
        final_status: CaseState,
        selected_action: ActionType | None = None,
        decision: RecoveryDecision | None = None,
        policy: PolicyResult | None = None,
        execution: ExecutionResult | None = None,
        outcome: RecoveryOutcome | None = None,
        action_id: str | None = None,
        recovered_amount: int = 0,
        waiting_until: datetime | None = None,
        message: str = "",
    ) -> WorkflowRun:
        payment = self._session.get(Payment, case.payment_id)
        return WorkflowRun(
            workflow_id=run.workflow_id,
            case_id=case.case_id,
            payment_id=case.payment_id,
            started_at=run.started_at,
            ended_at=self._clock.now(),
            state=case.state,
            final_status=final_status,
            recovered_amount=recovered_amount,
            currency=payment.currency if payment else self._settings.default_currency,
            selected_action=selected_action,
            decision=decision,
            policy=policy,
            execution=execution,
            outcome=outcome,
            action_id=action_id,
            waiting_until=waiting_until,
            stages=tuple(run.stages),
            message=message,
        )

    def _handle_stage_error(
        self,
        case: RecoveryCase,
        run: _RunState,
        entry_state: CaseState,
        error: Exception,
    ) -> None:
        """Leave the case recoverable and record what failed (Requirement 17.9).

        The state is restored directly rather than through the state machine: this
        is a rollback to a known-good state, not a lifecycle transition, and the
        machine deliberately has no edges for going backwards.

        ``ACTION_FAILED`` is used because Phase 0 has no dedicated stage-error event
        type; the metadata names the failing stage so the trail stays unambiguous.
        """
        failed_stage = run.stages[-1] if run.stages else "startup"

        logger.error(
            "[%s] stage failure | case=%s | stage=%s | %s: %s",
            run.workflow_id,
            case.case_id,
            failed_stage,
            type(error).__name__,
            error,
        )

        self._session.rollback()

        fresh = self._session.get(RecoveryCase, case.case_id)
        if fresh is not None:
            fresh.state = entry_state
            fresh.updated_at = self._clock.now()

            self._audit.record(
                case_id=fresh.case_id,
                payment_id=fresh.payment_id,
                stage=WorkflowStage.COMPLETION,
                event_type=AuditEventType.ACTION_FAILED,
                message=(
                    f"Workflow stage '{failed_stage}' raised {type(error).__name__}. "
                    f"The case was returned to {entry_state.value} and remains runnable."
                ),
                metadata={
                    "failed_stage": failed_stage,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                    "restored_state": entry_state.value,
                    "stages_completed": list(run.stages),
                },
                workflow_id=run.workflow_id,
            )
            self._session.commit()


__all__ = ["RUNNABLE_STATES", "CaseNotRunnable", "RevenueRecoveryWorkflow", "WorkflowRun"]
