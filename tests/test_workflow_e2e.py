"""End-to-end recovery workflow tests (Requirement 25.2-25.13).

These exercise the **real** Phase 0 application. Nothing is mocked: the risk
detector, context builder, diagnosis engine, candidate generator, deterministic
scorer, expected-value calculator, decision engine, policy engine, payment
simulator, outcome verifier, audit service, and analytics service are all the
production implementations, wired by ``RevenueRecoveryWorkflow`` exactly as the API
wires them.

Isolation comes from a temporary SQLite database and a virtual clock backed by a
temporary state file, not from substituting components (Requirement 25.14).
"""

from __future__ import annotations

import pytest

from app.core.enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    CaseState,
    ExecutionStatus,
    FailureReason,
    PaymentMethod,
    PaymentStatus,
    PolicyOutcome,
)
from app.core.errors import CaseAlreadyTerminal
from app.models import RecoveryAction, RecoveryOutcome
from app.services.analytics_service import AnalyticsService
from app.services.audit_service import AuditService
from app.services.risk_detector import RiskDetector
from app.services.scenario_generator import ScenarioGenerator
from app.workflows.recovery_workflow import RevenueRecoveryWorkflow


# ---------------------------------------------------------------------------
# Real-component fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def audit(db, clock) -> AuditService:
    return AuditService(session=db, clock=clock)


@pytest.fixture
def workflow(db, clock, settings) -> RevenueRecoveryWorkflow:
    """The production workflow with every real collaborator."""
    return RevenueRecoveryWorkflow(session=db, clock=clock, settings=settings)


@pytest.fixture
def open_case(db, clock, audit, payment_factory):
    """Create a failed payment and open its case through the real risk detector."""
    detector = RiskDetector(session=db, clock=clock, audit=audit)

    def _make(
        *,
        amount: int = 1_000_000,
        reason: FailureReason = FailureReason.BANK_TIMEOUT,
        method: PaymentMethod = PaymentMethod.UPI,
        attempts: int = 1,
        status: PaymentStatus = PaymentStatus.FAILED,
    ):
        payment = payment_factory(
            amount=amount,
            status=status,
            failure_reason=reason,
            payment_method=method,
            attempt_count=attempts,
        )
        case = detector.detect_and_open_case(payment)
        db.commit()
        return payment, case

    return _make


@pytest.fixture
def scenarios(db, clock, settings):
    """The four seeded deterministic scenarios, built by the real generator."""
    generator = ScenarioGenerator(session=db, clock=clock, settings=settings)
    built = generator.generate_demo_scenarios()
    db.commit()
    return {scenario.key: scenario for scenario in built}


# ===========================================================================
# 1. Complete BANK_TIMEOUT recovery (Requirement 25.2, 25.9)
# ===========================================================================


def test_complete_bank_timeout_recovery_through_the_full_pipeline(
    workflow, open_case, audit, clock, db
):
    """The headline happy path, every stage asserted in order.

    Risk detection -> diagnosis -> candidates -> prediction -> ERV -> decision ->
    policy approval -> RETRY_LATER -> SCHEDULED -> clock advance -> execution ->
    verification -> RECOVERED -> recovered revenue persisted.
    """
    payment, case = open_case(amount=1_000_000, reason=FailureReason.BANK_TIMEOUT)

    # --- risk detection already happened ---
    assert case.state is CaseState.DETECTED
    assert case.amount_at_risk == 1_000_000
    assert audit.event_types_for_case(case.case_id) == [AuditEventType.REVENUE_RISK_DETECTED]

    # --- run 1: diagnose, decide, gate, schedule ---
    first = workflow.run(case.case_id)

    # diagnosis persisted on the case
    db.refresh(case)
    assert case.diagnosis is not None
    assert case.diagnosis["failure_reason"] == "BANK_TIMEOUT"
    assert case.diagnosis["transience"] == "TRANSIENT"

    # candidates were evaluated, and more than one was considered
    ranked = first.decision.ranked
    assert {candidate.action for candidate in ranked} == {
        ActionType.RETRY_NOW,
        ActionType.RETRY_LATER,
        ActionType.SEND_PAYMENT_LINK,
    }

    # prediction populated
    assert 0.0 < first.decision.probability <= 1.0
    assert first.decision.model_version == "deterministic-scorer-v1"

    # expected recovery value computed with a full breakdown
    breakdown = first.decision.breakdown
    assert breakdown.payment_amount == 1_000_000
    assert breakdown.gross_expected_recovery == round(first.decision.probability * 1_000_000)
    assert breakdown.expected_recovery_value == (
        breakdown.gross_expected_recovery
        - breakdown.intervention_cost
        - breakdown.customer_friction_penalty
    )

    # decision selected the highest-value candidate
    assert first.selected_action is ActionType.RETRY_LATER
    assert first.decision.expected_recovery_value == max(
        candidate.expected_recovery_value for candidate in ranked
    )

    # policy approved, and scheduling followed
    assert first.policy.outcome is PolicyOutcome.APPROVED
    assert first.final_status is CaseState.SCHEDULED
    assert first.waiting_until == clock.now().replace(minute=15)

    # --- clock advance ---
    clock.advance(minutes=15)

    # --- run 2: execute and verify ---
    second = workflow.run(case.case_id)

    assert second.execution.status is ExecutionStatus.SUCCEEDED
    assert second.outcome.recovered is True
    assert second.outcome.previous_payment_status is PaymentStatus.FAILED
    assert second.outcome.new_payment_status is PaymentStatus.SUCCEEDED
    assert second.final_status is CaseState.RECOVERED
    assert second.recovered_amount == 1_000_000

    # --- recovered revenue persisted ---
    db.refresh(payment)
    assert payment.status is PaymentStatus.SUCCEEDED

    outcome = db.get(RecoveryOutcome, second.outcome.outcome_id)
    assert outcome is not None
    assert outcome.recovered is True
    assert outcome.recovered_amount == 1_000_000

    db.refresh(case)
    assert case.state is CaseState.RECOVERED
    assert case.terminal_outcome["recovered"] is True
    assert case.terminal_outcome["recovered_amount"] == 1_000_000


def test_recovered_case_rejects_further_runs(workflow, open_case, clock):
    """Requirement 17.5: a recovered case is terminal."""
    _, case = open_case(reason=FailureReason.BANK_TIMEOUT)
    workflow.run(case.case_id)
    clock.advance(minutes=15)
    workflow.run(case.case_id)

    with pytest.raises(CaseAlreadyTerminal):
        workflow.run(case.case_id)


# ===========================================================================
# 2. INSUFFICIENT_FUNDS stops at the retry limit (Requirement 25.3)
# ===========================================================================


def test_insufficient_funds_stops_at_the_retry_limit(workflow, open_case, audit, db, settings):
    """Retries fail repeatedly, the retry budget runs out, the case stops."""
    payment, case = open_case(
        amount=250_000,
        reason=FailureReason.INSUFFICIENT_FUNDS,
        method=PaymentMethod.CARD,
        attempts=settings.max_automatic_retries,
    )

    run = workflow.run(case.case_id)

    assert run.selected_action is ActionType.RETRY_LATER
    assert run.policy.outcome is PolicyOutcome.BLOCKED
    assert run.policy.rule_id == "retry_limit_reached"
    assert run.final_status is CaseState.STOPPED
    assert run.recovered_amount == 0
    assert run.execution is None
    assert run.outcome is None

    events = audit.event_types_for_case(case.case_id)
    assert AuditEventType.POLICY_BLOCKED in events
    assert AuditEventType.WORKFLOW_STOPPED in events
    assert AuditEventType.ACTION_EXECUTED not in events
    assert AuditEventType.REVENUE_RECOVERED not in events

    db.refresh(payment)
    assert payment.status is PaymentStatus.FAILED
    assert AnalyticsService(db).revenue().revenue_recovered == 0


def test_insufficient_funds_retry_fails_then_the_case_remains_re_runnable(
    workflow, open_case, db, clock
):
    """A real failed retry leaves the case available for another decision.

    The retry is scripted to fail, so this is deterministic. Afterwards the case
    sits in FAILED, which is re-runnable, and the candidate generator drops
    ``RETRY_LATER`` from future consideration because it has now failed on this
    payment.
    """
    payment, case = open_case(
        amount=250_000, reason=FailureReason.INSUFFICIENT_FUNDS, attempts=1
    )

    first = workflow.run(case.case_id)
    assert first.selected_action is ActionType.RETRY_LATER
    assert first.final_status is CaseState.SCHEDULED

    clock.advance(minutes=15)
    second = workflow.run(case.case_id)

    assert second.execution.status is ExecutionStatus.FAILED
    assert second.outcome.recovered is False
    assert second.recovered_amount == 0
    assert second.final_status is CaseState.FAILED

    db.refresh(payment)
    assert payment.attempt_count == 2

    # A third run re-decides with the updated history, excluding the failed retry.
    third = workflow.run(case.case_id)
    considered = {candidate.action for candidate in third.decision.ranked}
    assert ActionType.RETRY_LATER not in considered

    # ...but the exhausted budget blocks whatever it picks instead.
    assert third.policy.outcome is PolicyOutcome.BLOCKED
    assert third.final_status is CaseState.STOPPED


def test_exhausted_recovery_budget_cannot_be_bypassed_by_another_action(
    workflow, open_case, audit, db, settings
):
    """The invariant: once the budget is spent, no automatic action may run.

    Bounding only *retries* was bypassable. A case whose retry budget was exhausted
    could keep going through non-retry channels (payment link, then reminder), each
    an automatic action against a payment the system had already agreed to stop
    pushing. ``recovery_budget_exhausted`` closes that path.

    Here the payment arrives with its budget already spent, and the failure reason
    offers two non-retry alternatives. Neither may execute.
    """
    payment, case = open_case(
        amount=250_000,
        reason=FailureReason.INSUFFICIENT_FUNDS,
        attempts=settings.max_automatic_retries,
    )
    attempts_before = payment.attempt_count

    run = workflow.run(case.case_id)

    assert run.policy.outcome is PolicyOutcome.BLOCKED
    assert run.policy.rule_id in {"retry_limit_reached", "recovery_budget_exhausted"}
    assert run.final_status is CaseState.STOPPED
    assert run.execution is None
    assert run.recovered_amount == 0

    # Nothing was charged.
    db.refresh(payment)
    assert payment.attempt_count == attempts_before
    assert payment.status is PaymentStatus.FAILED

    events = audit.event_types_for_case(case.case_id)
    assert AuditEventType.ACTION_EXECUTED not in events
    assert AuditEventType.ACTION_FAILED not in events
    assert AuditEventType.WORKFLOW_STOPPED in events


@pytest.mark.parametrize(
    "action",
    [
        ActionType.SEND_PAYMENT_LINK,
        ActionType.SEND_REMINDER,
        ActionType.CHANGE_PAYMENT_METHOD,
        ActionType.RETRY_NOW,
        ActionType.RETRY_LATER,
    ],
)
def test_no_automatic_action_survives_an_exhausted_budget(
    db, clock, settings, open_case, action
):
    """Every automatic action is blocked at the budget, not just retries."""
    from dataclasses import replace as dc_replace

    from app.services.context_builder import RecoveryContextBuilder
    from app.services.decision_engine import RecoveryDecisionEngine
    from app.services.diagnosis_engine import RuleBasedDiagnosisEngine
    from app.services.expected_value import ExpectedRecoveryCalculator
    from app.ml.deterministic_scorer import DeterministicRecoveryScorer
    from app.services.policy_engine import PolicyEngine

    _, case = open_case(
        reason=FailureReason.INSUFFICIENT_FUNDS, attempts=settings.max_automatic_retries
    )
    context = RecoveryContextBuilder(db, clock).build(case)
    diagnosis = RuleBasedDiagnosisEngine().diagnose(context)

    engine = RecoveryDecisionEngine(
        predictor=DeterministicRecoveryScorer(),
        calculator=ExpectedRecoveryCalculator(settings),
        settings=settings,
    )
    decision = engine.decide(context, diagnosis, [action])
    result = PolicyEngine(settings=settings).evaluate(context, decision)

    assert result.outcome is PolicyOutcome.BLOCKED
    assert result.rule_id in {"retry_limit_reached", "recovery_budget_exhausted"}


def test_terminal_dispositions_remain_available_after_the_budget_is_spent(
    db, clock, settings, open_case
):
    """An exhausted case must still be able to stop or escalate."""
    from app.ml.deterministic_scorer import DeterministicRecoveryScorer
    from app.services.context_builder import RecoveryContextBuilder
    from app.services.decision_engine import RecoveryDecisionEngine
    from app.services.diagnosis_engine import RuleBasedDiagnosisEngine
    from app.services.expected_value import ExpectedRecoveryCalculator
    from app.services.policy_engine import PolicyEngine

    _, case = open_case(
        reason=FailureReason.INSUFFICIENT_FUNDS, attempts=settings.max_automatic_retries
    )
    context = RecoveryContextBuilder(db, clock).build(case)
    diagnosis = RuleBasedDiagnosisEngine().diagnose(context)
    engine = RecoveryDecisionEngine(
        predictor=DeterministicRecoveryScorer(),
        calculator=ExpectedRecoveryCalculator(settings),
        settings=settings,
    )
    policy = PolicyEngine(settings=settings)

    for action in (ActionType.ESCALATE_HUMAN, ActionType.STOP):
        decision = engine.decide(context, diagnosis, [action])
        assert policy.evaluate(context, decision).rule_id != "recovery_budget_exhausted"


def test_executor_is_never_called_after_budget_exhaustion(db, clock, settings, open_case, audit):
    """The gate sits upstream of execution, so the executor is not merely ignored.

    A tripwire executor raises the moment it is touched. Reaching STOPPED without it
    firing proves the refusal happens *before* execution, rather than being undone
    afterwards. This is the boundary that matters: ActionExecutor executes only
    policy-approved actions.
    """
    from app.integrations.action_executor import ExecutionResult  # noqa: F401

    calls: list[str] = []

    class TripwireExecutor:
        """Real ActionExecutor shape. Raises if invoked."""

        @property
        def supported_actions(self):
            return frozenset(ActionType)

        def supports(self, action):
            return True

        def schedule(self, action, context, scheduled_at):
            calls.append(f"schedule:{action.value}")
            raise AssertionError("executor.schedule called after budget exhaustion")

        def execute(self, action, context, *, audit=None, workflow_id=None):
            calls.append(f"execute:{action.value}")
            raise AssertionError("executor.execute called after budget exhaustion")

    payment, case = open_case(
        amount=250_000,
        reason=FailureReason.INSUFFICIENT_FUNDS,
        attempts=settings.max_automatic_retries,
    )
    attempts_before = payment.attempt_count

    workflow = RevenueRecoveryWorkflow(
        session=db, clock=clock, settings=settings, executor=TripwireExecutor()
    )
    run = workflow.run(case.case_id)

    # The executor was never touched.
    assert calls == []

    # Policy blocked, case stopped.
    assert run.policy.outcome is PolicyOutcome.BLOCKED
    assert run.final_status is CaseState.STOPPED
    assert run.execution is None
    assert run.outcome is None
    assert run.recovered_amount == 0

    # No RecoveryAction was executed.
    executed = (
        db.query(RecoveryAction)
        .filter_by(case_id=case.case_id)
        .filter(RecoveryAction.executed_at.is_not(None))
        .count()
    )
    assert executed == 0

    # No ACTION_EXECUTED event exists.
    events = audit.event_types_for_case(case.case_id)
    assert AuditEventType.ACTION_EXECUTED not in events
    assert AuditEventType.ACTION_FAILED not in events
    assert AuditEventType.OUTCOME_VERIFIED not in events

    # The payment itself is untouched.
    db.refresh(payment)
    assert payment.attempt_count == attempts_before
    assert payment.status is PaymentStatus.FAILED


def test_no_action_executed_event_after_budget_exhaustion_mid_lifecycle(
    workflow, open_case, audit, db, clock, settings
):
    """Budget exhaustion reached through real execution, not a preset attempt count.

    The first retry genuinely runs and fails, spending the budget. From that point
    on, no further ACTION_EXECUTED event may appear however many times the case is
    run.
    """
    payment, case = open_case(
        amount=250_000, reason=FailureReason.INSUFFICIENT_FUNDS, attempts=1
    )

    workflow.run(case.case_id)
    clock.advance(minutes=settings.retry_later_delay_minutes)
    workflow.run(case.case_id)

    db.refresh(payment)
    assert payment.attempt_count == settings.max_automatic_retries

    executed_before = audit.event_types_for_case(case.case_id).count(
        AuditEventType.ACTION_EXECUTED
    ) + audit.event_types_for_case(case.case_id).count(AuditEventType.ACTION_FAILED)

    # Every subsequent run must refuse.
    for _ in range(3):
        db.refresh(case)
        if case.state in CaseState.terminal():
            break
        run = workflow.run(case.case_id)
        assert run.policy.outcome is PolicyOutcome.BLOCKED
        assert run.execution is None

    events = audit.event_types_for_case(case.case_id)
    executed_after = events.count(AuditEventType.ACTION_EXECUTED) + events.count(
        AuditEventType.ACTION_FAILED
    )
    assert executed_after == executed_before

    db.refresh(case)
    assert case.state is CaseState.STOPPED
    assert AuditEventType.WORKFLOW_STOPPED in events
    assert payment.attempt_count == settings.max_automatic_retries


def test_candidate_generation_is_unchanged_by_the_budget_rule(db, clock, settings, open_case):
    """The generator proposes; only the gate refuses.

    Candidate generation stays a function of diagnosis and recovery history alone.
    Pushing the budget check down into the generator would have hidden the refusal
    from the audit trail and blurred the boundary, so the candidate set must be
    identical whether the budget is spent or not.
    """
    from app.services.candidate_generator import (
        CANDIDATES_BY_REASON,
        RecoveryActionCandidateGenerator,
    )
    from app.services.context_builder import RecoveryContextBuilder
    from app.services.diagnosis_engine import RuleBasedDiagnosisEngine

    generator = RecoveryActionCandidateGenerator()
    diagnoser = RuleBasedDiagnosisEngine()
    builder = RecoveryContextBuilder(db, clock)

    _, fresh_case = open_case(reason=FailureReason.INSUFFICIENT_FUNDS, attempts=1)
    _, spent_case = open_case(
        reason=FailureReason.INSUFFICIENT_FUNDS, attempts=settings.max_automatic_retries
    )

    fresh_context = builder.build(fresh_case)
    spent_context = builder.build(spent_case)

    assert fresh_context.attempt_count != spent_context.attempt_count

    fresh = generator.generate(fresh_context, diagnoser.diagnose(fresh_context))
    spent = generator.generate(spent_context, diagnoser.diagnose(spent_context))

    assert fresh == spent
    assert spent == list(CANDIDATES_BY_REASON[FailureReason.INSUFFICIENT_FUNDS])


def test_candidate_generator_has_no_knowledge_of_recovery_budget():
    """The boundary, enforced structurally rather than by convention."""
    import ast
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "candidate_generator.py"
    )
    source = path.read_text(encoding="utf-8")

    for forbidden in (
        "max_automatic_retries",
        "recovery_budget",
        "repeated_failure_limit",
        "PolicyEngine",
        "PolicyOutcome",
    ):
        assert forbidden not in source, f"candidate generator references {forbidden}"

    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("policy" in module for module in imported)


def test_decision_engine_still_ranks_economically_after_budget_exhaustion(
    db, clock, settings, open_case
):
    """Ranking is unaffected: the economics of a candidate do not change.

    Preserves the boundary that DecisionEngine selects the economically preferable
    action and PolicyEngine decides whether it is permitted.
    """
    from app.ml.deterministic_scorer import DeterministicRecoveryScorer
    from app.services.candidate_generator import RecoveryActionCandidateGenerator
    from app.services.context_builder import RecoveryContextBuilder
    from app.services.decision_engine import RecoveryDecisionEngine
    from app.services.diagnosis_engine import RuleBasedDiagnosisEngine
    from app.services.expected_value import ExpectedRecoveryCalculator

    _, case = open_case(
        reason=FailureReason.INSUFFICIENT_FUNDS, attempts=settings.max_automatic_retries
    )
    context = RecoveryContextBuilder(db, clock).build(case)
    diagnosis = RuleBasedDiagnosisEngine().diagnose(context)
    candidates = RecoveryActionCandidateGenerator().generate(context, diagnosis)

    decision = RecoveryDecisionEngine(
        predictor=DeterministicRecoveryScorer(),
        calculator=ExpectedRecoveryCalculator(settings),
        settings=settings,
    ).decide(context, diagnosis, candidates)

    # A selection is still made, ranked by expected recovery value.
    assert decision.selected_action in candidates
    values = [candidate.expected_recovery_value for candidate in decision.ranked]
    assert values == sorted(values, reverse=True)


def test_budget_rule_precedes_every_permitting_rule():
    """Requirement 13.12: ordering is what makes the boundary unbypassable."""
    from app.services.policy_rules import DEFAULT_APPROVE_RULE_ID, RULE_ORDER

    assert "recovery_budget_exhausted" in RULE_ORDER
    budget_index = RULE_ORDER.index("recovery_budget_exhausted")

    # Nothing may approve before the budget rule has had its say.
    assert budget_index < RULE_ORDER.index(DEFAULT_APPROVE_RULE_ID)
    assert RULE_ORDER[-1] == DEFAULT_APPROVE_RULE_ID

    # Escalation rules follow the blocking rules.
    assert budget_index < RULE_ORDER.index("unknown_failure")
    assert budget_index < RULE_ORDER.index("high_value_transaction")


def test_recovery_always_terminates_within_the_configured_limits(
    workflow, open_case, audit, db, clock, settings
):
    """The termination guarantee: no case can be chased forever.

    Drives the case to completion, advancing the clock whenever a delayed retry is
    pending. Whichever rule fires, the case must reach a terminal state rather than
    cycling, and no retry may execute past the configured budget.
    """
    payment, case = open_case(
        amount=250_000, reason=FailureReason.INSUFFICIENT_FUNDS, attempts=1
    )

    budget = settings.max_automatic_retries + settings.repeated_failure_limit + 6

    for _ in range(budget):
        db.refresh(case)
        if case.state in CaseState.terminal():
            break
        run = workflow.run(case.case_id)
        if run.waiting:
            clock.advance(minutes=settings.retry_later_delay_minutes)

    db.refresh(case)
    assert case.state in CaseState.terminal(), (
        f"case did not terminate within {budget} runs; state={case.state.value}"
    )

    if case.state is CaseState.STOPPED:
        stopped = next(
            event
            for event in audit.for_case(case.case_id)
            if event.event_type is AuditEventType.WORKFLOW_STOPPED
        )
        assert stopped.meta["policy_rule_id"] in {
            "retry_limit_reached",
            "recovery_budget_exhausted",
            "repeated_failure_limit",
        }

    executed_retries = (
        db.query(RecoveryAction)
        .filter_by(case_id=case.case_id)
        .filter(RecoveryAction.action_type.in_(tuple(ActionType.retry_actions())))
        .filter(RecoveryAction.executed_at.is_not(None))
        .count()
    )
    assert executed_retries <= settings.max_automatic_retries


def test_stopped_case_is_terminal(workflow, open_case, settings):
    _, case = open_case(
        reason=FailureReason.INSUFFICIENT_FUNDS, attempts=settings.max_automatic_retries
    )
    workflow.run(case.case_id)

    with pytest.raises(CaseAlreadyTerminal):
        workflow.run(case.case_id)


# ===========================================================================
# 3. High-value escalation (Requirement 25.4)
# ===========================================================================


def test_high_value_transaction_escalates_without_executing(
    workflow, open_case, audit, db, settings
):
    """The policy gate holds: no execution, and no ACTION_EXECUTED event."""
    payment, case = open_case(
        amount=settings.high_value_escalation_threshold + 4_000_000,
        reason=FailureReason.BANK_TIMEOUT,
    )
    attempts_before = payment.attempt_count

    run = workflow.run(case.case_id)

    assert run.policy.outcome is PolicyOutcome.ESCALATED
    assert run.policy.rule_id == "high_value_transaction"
    assert run.final_status is CaseState.ESCALATED
    assert run.execution is None
    assert run.outcome is None
    assert run.recovered_amount == 0

    events = audit.event_types_for_case(case.case_id)
    assert AuditEventType.POLICY_ESCALATED in events
    assert AuditEventType.ACTION_EXECUTED not in events
    assert AuditEventType.ACTION_FAILED not in events
    assert AuditEventType.OUTCOME_VERIFIED not in events
    assert AuditEventType.REVENUE_RECOVERED not in events

    # The payment was never touched.
    db.refresh(payment)
    assert payment.status is PaymentStatus.FAILED
    assert payment.attempt_count == attempts_before

    # No verified outcome exists at all.
    assert db.query(RecoveryOutcome).count() == 0

    # The action records the escalation for a human to pick up.
    action = db.query(RecoveryAction).filter_by(case_id=case.case_id).one()
    assert action.policy_outcome is PolicyOutcome.ESCALATED
    assert action.status is ActionStatus.ESCALATED
    assert action.requires_human_approval is True
    assert action.executed_at is None


def test_escalated_case_is_terminal(workflow, open_case, settings):
    _, case = open_case(amount=settings.high_value_escalation_threshold + 1)
    workflow.run(case.case_id)

    with pytest.raises(CaseAlreadyTerminal):
        workflow.run(case.case_id)


# ===========================================================================
# 4. EXPIRED_CARD recovers via a new instrument (Requirement 25.13)
# ===========================================================================


def test_expired_card_recovers_through_change_payment_method(workflow, open_case, audit, db):
    payment, case = open_case(
        amount=600_000, reason=FailureReason.EXPIRED_CARD, method=PaymentMethod.CARD
    )

    run = workflow.run(case.case_id)

    assert run.selected_action is ActionType.CHANGE_PAYMENT_METHOD
    assert run.policy.outcome is PolicyOutcome.APPROVED
    assert run.execution.status is ExecutionStatus.SUCCEEDED
    assert run.outcome.recovered is True
    assert run.final_status is CaseState.RECOVERED
    assert run.recovered_amount == 600_000

    db.refresh(payment)
    assert payment.status is PaymentStatus.SUCCEEDED
    assert payment.attempts[-1].action_type is ActionType.CHANGE_PAYMENT_METHOD

    assert AuditEventType.REVENUE_RECOVERED in audit.event_types_for_case(case.case_id)


def test_expired_card_never_selects_a_plain_retry(workflow, open_case):
    """Retrying a dead instrument is not among the candidates at all."""
    _, case = open_case(reason=FailureReason.EXPIRED_CARD)
    run = workflow.run(case.case_id)

    considered = {candidate.action for candidate in run.decision.ranked}
    assert ActionType.RETRY_NOW not in considered
    assert ActionType.RETRY_LATER not in considered


# ===========================================================================
# 5 & 6. Virtual clock behaviour (Requirement 25.9, 18.5, 18.8)
# ===========================================================================


def test_scheduled_action_does_not_execute_before_its_due_time(
    workflow, open_case, audit, db, clock
):
    """Requirement 18.5: the case waits, and nothing is charged."""
    payment, case = open_case(reason=FailureReason.BANK_TIMEOUT)

    first = workflow.run(case.case_id)
    assert first.final_status is CaseState.SCHEDULED
    due = first.waiting_until
    attempts_after_schedule = db.get(type(payment), payment.payment_id).attempt_count

    # Several runs before the due time change nothing.
    for _ in range(3):
        waiting = workflow.run(case.case_id)
        assert waiting.waiting is True
        assert waiting.waiting_until == due
        assert waiting.final_status is CaseState.SCHEDULED
        assert waiting.execution is None
        assert waiting.outcome is None

    db.refresh(case)
    assert case.state is CaseState.SCHEDULED

    db.refresh(payment)
    assert payment.status is PaymentStatus.FAILED
    assert payment.attempt_count == attempts_after_schedule

    events = audit.event_types_for_case(case.case_id)
    assert AuditEventType.ACTION_SCHEDULED in events
    assert AuditEventType.ACTION_EXECUTED not in events


def test_partial_clock_advance_still_waits(workflow, open_case, clock):
    _, case = open_case(reason=FailureReason.BANK_TIMEOUT)
    workflow.run(case.case_id)

    clock.advance(minutes=14)
    assert workflow.run(case.case_id).waiting is True

    clock.advance(minutes=1)
    assert workflow.run(case.case_id).final_status is CaseState.RECOVERED


def test_scheduled_action_executes_exactly_once_after_the_clock_advances(
    workflow, open_case, audit, db, clock
):
    """Requirement 18.8: due means executed, and only once."""
    payment, case = open_case(reason=FailureReason.BANK_TIMEOUT)
    workflow.run(case.case_id)
    clock.advance(minutes=15)

    run = workflow.run(case.case_id)
    assert run.execution.status is ExecutionStatus.SUCCEEDED
    assert run.final_status is CaseState.RECOVERED

    # Exactly one execution, one action, one outcome.
    events = audit.event_types_for_case(case.case_id)
    assert events.count(AuditEventType.ACTION_EXECUTED) == 1
    assert events.count(AuditEventType.REVENUE_RECOVERED) == 1

    actions = db.query(RecoveryAction).filter_by(case_id=case.case_id).all()
    assert len(actions) == 1
    assert actions[0].executed_at is not None
    assert actions[0].scheduled_at is not None

    assert db.query(RecoveryOutcome).count() == 1

    db.refresh(payment)
    assert payment.attempt_count == 2  # the original failure plus one retry


def test_scheduling_does_not_re_decide_on_resumption(workflow, open_case, clock, db):
    """The action a reviewer saw approved is the action that runs."""
    _, case = open_case(reason=FailureReason.BANK_TIMEOUT)
    first = workflow.run(case.case_id)
    action_id = first.action_id

    clock.advance(minutes=15)
    second = workflow.run(case.case_id)

    assert second.action_id == action_id
    assert db.query(RecoveryAction).filter_by(case_id=case.case_id).count() == 1


# ===========================================================================
# 7. Audit trail (Requirement 25.1, 19.2, 19.7, 23.1)
# ===========================================================================


def test_successful_recovery_produces_the_expected_audit_sequence(
    workflow, open_case, audit, clock
):
    """Requirement 25.2: all nine events, in order."""
    _, case = open_case(reason=FailureReason.BANK_TIMEOUT)
    workflow.run(case.case_id)
    clock.advance(minutes=15)
    workflow.run(case.case_id)

    assert audit.event_types_for_case(case.case_id) == [
        AuditEventType.REVENUE_RISK_DETECTED,
        AuditEventType.DIAGNOSIS_COMPLETED,
        AuditEventType.RECOVERY_OPTIONS_EVALUATED,
        AuditEventType.RECOVERY_DECISION_SELECTED,
        AuditEventType.POLICY_APPROVED,
        AuditEventType.ACTION_SCHEDULED,
        AuditEventType.ACTION_EXECUTED,
        AuditEventType.OUTCOME_VERIFIED,
        AuditEventType.REVENUE_RECOVERED,
    ]


def test_audit_sequence_ordering_is_deterministic(workflow, open_case, audit, clock):
    """Requirement 19.7: stable even when simulation timestamps tie."""
    _, case = open_case(reason=FailureReason.BANK_TIMEOUT)
    workflow.run(case.case_id)
    clock.advance(minutes=15)
    workflow.run(case.case_id)

    events = audit.for_case(case.case_id)
    sequences = [event.sequence for event in events]

    assert sequences == list(range(1, len(events) + 1))
    assert sequences == sorted(sequences)
    # Several events share one simulation timestamp, so ordering relies on sequence.
    assert len({event.timestamp for event in events}) < len(events)


def test_audit_events_are_persisted_and_readable_after_a_fresh_query(
    workflow, open_case, db, clock, audit
):
    _, case = open_case(reason=FailureReason.BANK_TIMEOUT)
    workflow.run(case.case_id)
    clock.advance(minutes=15)
    workflow.run(case.case_id)

    from app.models import AuditEvent

    persisted = (
        db.query(AuditEvent)
        .filter_by(case_id=case.case_id)
        .order_by(AuditEvent.sequence)
        .all()
    )
    assert len(persisted) == 9
    assert all(event.message for event in persisted)
    assert all(event.stage is not None for event in persisted)


def test_workflow_id_is_reconstructable_from_the_audit_trail(workflow, open_case, audit, clock):
    """Requirement 23.1: the workflow record needs no separate table."""
    _, case = open_case(reason=FailureReason.BANK_TIMEOUT)
    first = workflow.run(case.case_id)
    clock.advance(minutes=15)
    second = workflow.run(case.case_id)

    events = audit.for_case(case.case_id)
    workflow_ids = {event.workflow_id for event in events if event.workflow_id}

    # Detection predates any run, so it carries no workflow id; the two runs do.
    assert workflow_ids == {first.workflow_id, second.workflow_id}

    run_one = [event for event in events if event.workflow_id == first.workflow_id]
    run_two = [event for event in events if event.workflow_id == second.workflow_id]
    assert len(run_one) == 5  # diagnosis, evaluated, selected, policy, scheduled
    assert len(run_two) == 3  # executed, verified, recovered


def test_decision_metadata_is_captured_in_the_audit_trail(workflow, open_case, audit):
    """Requirement 19.3."""
    _, case = open_case(reason=FailureReason.BANK_TIMEOUT)
    run = workflow.run(case.case_id)

    selected = next(
        event
        for event in audit.for_case(case.case_id)
        if event.event_type is AuditEventType.RECOVERY_DECISION_SELECTED
    )
    metadata = selected.meta

    assert metadata["selected_action"] == run.selected_action.value
    assert metadata["expected_recovery_value"] == run.decision.expected_recovery_value
    assert metadata["probability"] == run.decision.probability
    assert metadata["confidence"] == run.decision.confidence
    assert metadata["model_version"] == "deterministic-scorer-v1"
    assert metadata["alternatives"]
    assert metadata["explanation"]


def test_policy_metadata_records_the_deciding_rule(workflow, open_case, audit, settings):
    """Requirement 19.4."""
    _, case = open_case(
        reason=FailureReason.INSUFFICIENT_FUNDS, attempts=settings.max_automatic_retries
    )
    workflow.run(case.case_id)

    blocked = next(
        event
        for event in audit.for_case(case.case_id)
        if event.event_type is AuditEventType.POLICY_BLOCKED
    )
    assert blocked.meta["policy_rule_id"] == "retry_limit_reached"
    assert blocked.meta["policy_outcome"] == "BLOCKED"
    assert blocked.meta["limits"]["max_automatic_retries"] == settings.max_automatic_retries


# ===========================================================================
# 8. Outcome verification independence (Requirement 25.12)
# ===========================================================================


def test_verifier_reads_persisted_payment_state_not_the_execution_result(
    db, clock, settings, open_case, audit
):
    """Executor success alone cannot manufacture recovery.

    A deliberately dishonest executor reports SUCCEEDED without touching the
    payment. The real verifier re-reads the database and reports no recovery, so the
    recovered total stays truthful.
    """
    from app.core.enums import ExecutionStatus as ES
    from app.integrations.action_executor import ExecutionResult

    class LyingExecutor:
        """Reports success, changes nothing. Not a mock of the verifier."""

        @property
        def supported_actions(self):
            return frozenset(ActionType)

        def supports(self, action):
            return True

        def schedule(self, action, context, scheduled_at):
            return ExecutionResult(
                action=action,
                status=ES.SCHEDULED,
                provider_response={"simulated": True},
                executed_at=clock.now(),
            )

        def execute(self, action, context, *, audit=None, workflow_id=None):
            return ExecutionResult(
                action=action,
                status=ES.SUCCEEDED,  # a lie
                provider_response={"simulated": True, "claimed": "succeeded"},
                executed_at=clock.now(),
            )

    payment, case = open_case(reason=FailureReason.EXPIRED_CARD, amount=600_000)

    workflow = RevenueRecoveryWorkflow(
        session=db, clock=clock, settings=settings, executor=LyingExecutor()
    )
    run = workflow.run(case.case_id)

    # The executor claimed success...
    assert run.execution.status is ExecutionStatus.SUCCEEDED
    # ...but the persisted payment never changed, so nothing was recovered.
    db.refresh(payment)
    assert payment.status is PaymentStatus.FAILED
    assert run.outcome.recovered is False
    assert run.recovered_amount == 0
    assert run.final_status is CaseState.FAILED

    assert AuditEventType.REVENUE_RECOVERED not in audit.event_types_for_case(case.case_id)
    assert AnalyticsService(db).revenue().revenue_recovered == 0


def test_recovered_amount_comes_from_the_verified_payment(workflow, open_case, db, clock):
    """Recovered revenue is the payment's own amount, read after execution."""
    payment, case = open_case(amount=777_700, reason=FailureReason.BANK_TIMEOUT)
    workflow.run(case.case_id)
    clock.advance(minutes=15)
    run = workflow.run(case.case_id)

    assert run.outcome.recovered_amount == 777_700
    assert run.outcome.recovered_amount == payment.amount


# ===========================================================================
# 9. Analytics from persisted state (Requirement 25.1, 20.4)
# ===========================================================================


def test_analytics_are_computed_from_persisted_rows(workflow, open_case, db, clock, settings):
    """Requirement 20.4: no hardcoded totals, no in-memory counters."""
    recovered_payment, recovered_case = open_case(
        amount=1_000_000, reason=FailureReason.BANK_TIMEOUT
    )
    _, stopped_case = open_case(
        amount=250_000,
        reason=FailureReason.INSUFFICIENT_FUNDS,
        attempts=settings.max_automatic_retries,
    )
    _, escalated_case = open_case(
        amount=settings.high_value_escalation_threshold + 1_000_000,
        reason=FailureReason.BANK_TIMEOUT,
    )

    workflow.run(recovered_case.case_id)
    clock.advance(minutes=15)
    workflow.run(recovered_case.case_id)
    workflow.run(stopped_case.case_id)
    workflow.run(escalated_case.case_id)

    revenue = AnalyticsService(db).revenue()
    recovery = AnalyticsService(db).recovery()

    expected_at_risk = (
        1_000_000 + 250_000 + settings.high_value_escalation_threshold + 1_000_000
    )
    assert revenue.revenue_at_risk == expected_at_risk
    assert revenue.revenue_recovered == 1_000_000
    assert revenue.recovery_rate == pytest.approx(round(1_000_000 / expected_at_risk, 4))
    assert revenue.cases_total == 3
    assert revenue.cases_recovered == 1
    assert revenue.average_recovery_value == 1_000_000

    assert recovery.actions.stopped == 1
    assert recovery.actions.escalated == 1
    assert recovery.actions.successful == 1
    assert recovery.cases_by_state == {"RECOVERED": 1, "STOPPED": 1, "ESCALATED": 1}


def test_analytics_totals_are_derived_not_asserted(workflow, open_case, db, clock):
    """Totals must equal the sum of the underlying rows, computed independently."""
    for amount in (100_000, 250_000, 600_000):
        _, case = open_case(amount=amount, reason=FailureReason.BANK_TIMEOUT)
        workflow.run(case.case_id)
        clock.advance(minutes=15)
        workflow.run(case.case_id)

    from sqlalchemy import func, select

    from app.models import RecoveryCase

    at_risk_from_rows = db.execute(
        select(func.sum(RecoveryCase.amount_at_risk))
    ).scalar_one()
    recovered_from_rows = db.execute(
        select(func.sum(RecoveryOutcome.recovered_amount)).where(
            RecoveryOutcome.recovered.is_(True)
        )
    ).scalar_one()

    revenue = AnalyticsService(db).revenue()
    assert revenue.revenue_at_risk == at_risk_from_rows
    assert revenue.revenue_recovered == recovered_from_rows
    assert revenue.revenue_recovered == 950_000


def test_analytics_report_zero_before_any_recovery(db):
    revenue = AnalyticsService(db).revenue()
    assert revenue.revenue_at_risk == 0
    assert revenue.revenue_recovered == 0
    assert revenue.recovery_rate == 0.0


# ===========================================================================
# The four seeded scenarios, driven by the real workflow
# ===========================================================================


def test_seeded_scenario_a_recovers(workflow, scenarios, clock, db):
    scenario = scenarios["A"]
    assert scenario.case.case_id == "case_demo_a"

    first = workflow.run(scenario.case.case_id)
    assert first.selected_action.value == scenario.expected_action
    assert first.final_status is CaseState.SCHEDULED

    clock.advance(minutes=15)
    second = workflow.run(scenario.case.case_id)

    assert second.final_status.value == scenario.expected_final_state
    assert second.recovered_amount == 1_000_000


def test_seeded_scenario_b_stops(workflow, scenarios, db):
    scenario = scenarios["B"]
    assert scenario.case.case_id == "case_demo_b"

    run = workflow.run(scenario.case.case_id)
    assert run.final_status.value == scenario.expected_final_state
    assert run.policy.rule_id == "retry_limit_reached"
    assert run.recovered_amount == 0


def test_seeded_scenario_c_escalates(workflow, scenarios, audit):
    scenario = scenarios["C"]
    assert scenario.case.case_id == "case_demo_c"

    run = workflow.run(scenario.case.case_id)
    assert run.final_status.value == scenario.expected_final_state
    assert run.policy.rule_id == "high_value_transaction"
    assert run.execution is None
    assert AuditEventType.ACTION_EXECUTED not in audit.event_types_for_case(
        scenario.case.case_id
    )


def test_seeded_scenario_d_recovers_via_alternative_instrument(workflow, scenarios):
    scenario = scenarios["D"]
    assert scenario.case.case_id == "case_demo_d"

    run = workflow.run(scenario.case.case_id)
    assert run.selected_action.value == scenario.expected_action
    assert run.final_status.value == scenario.expected_final_state
    assert run.recovered_amount == 600_000


def test_all_four_seeded_scenarios_are_reproducible(workflow, scenarios, clock, db):
    """Requirement 27.2: the same seed yields the same outcomes."""
    results = {}
    for key in ("A", "B", "C", "D"):
        case_id = scenarios[key].case.case_id
        run = workflow.run(case_id)
        if run.final_status is CaseState.SCHEDULED:
            clock.advance(minutes=15)
            run = workflow.run(case_id)
        results[key] = (run.final_status.value, run.recovered_amount)

    assert results == {
        "A": ("RECOVERED", 1_000_000),
        "B": ("STOPPED", 0),
        "C": ("ESCALATED", 0),
        "D": ("RECOVERED", 600_000),
    }


# ===========================================================================
# State machine enforcement through the real workflow (Requirement 25.10)
# ===========================================================================


def test_execution_never_bypasses_decision_and_policy(workflow, open_case, audit, clock):
    """Every ACTION_EXECUTED is preceded by a decision and a policy approval."""
    _, case = open_case(reason=FailureReason.BANK_TIMEOUT)
    workflow.run(case.case_id)
    clock.advance(minutes=15)
    workflow.run(case.case_id)

    events = audit.event_types_for_case(case.case_id)
    executed_at = events.index(AuditEventType.ACTION_EXECUTED)

    assert events.index(AuditEventType.RECOVERY_DECISION_SELECTED) < executed_at
    assert events.index(AuditEventType.POLICY_APPROVED) < executed_at


def test_case_not_runnable_from_an_intermediate_state(workflow, open_case, db):
    from app.workflows.recovery_workflow import CaseNotRunnable

    _, case = open_case(reason=FailureReason.BANK_TIMEOUT)
    case.state = CaseState.EVALUATING
    db.commit()

    with pytest.raises(CaseNotRunnable):
        workflow.run(case.case_id)


def test_unknown_case_raises_not_found(workflow):
    from app.core.errors import RecordNotFound

    with pytest.raises(RecordNotFound):
        workflow.run("case_does_not_exist")
