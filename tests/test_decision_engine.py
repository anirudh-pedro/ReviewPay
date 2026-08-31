"""Decision engine tests (Requirement 11.1-11.6, 12.1-12.3, 25.8)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.core.enums import ActionType, FailureReason, RiskLevel
from app.ml.deterministic_scorer import DeterministicRecoveryScorer
from app.services.candidate_generator import RecoveryActionCandidateGenerator
from app.services.decision_engine import (
    RecoveryDecision,
    RecoveryDecisionEngine,
    ScoredCandidate,
)
from app.services.diagnosis_engine import RuleBasedDiagnosisEngine
from app.services.expected_value import ExpectedRecoveryCalculator
from tests.test_predictor import context_with


@pytest.fixture
def engine(settings) -> RecoveryDecisionEngine:
    return RecoveryDecisionEngine(
        predictor=DeterministicRecoveryScorer(),
        calculator=ExpectedRecoveryCalculator(settings),
        settings=settings,
    )


@pytest.fixture
def diagnose():
    return RuleBasedDiagnosisEngine().diagnose


@pytest.fixture
def generate():
    return RecoveryActionCandidateGenerator().generate


def decide_for(engine, diagnose, generate, reason=FailureReason.BANK_TIMEOUT, **kwargs):
    context = context_with(reason=reason, **kwargs)
    diagnosis = diagnose(context)
    candidates = generate(context, diagnosis)
    return context, engine.decide(context, diagnosis, candidates)


# ---------------------------------------------------------------------------
# Scoring and ranking
# ---------------------------------------------------------------------------


def test_every_candidate_is_scored_and_ranked(engine, diagnose, generate):
    """Requirement 11.1."""
    _, decision = decide_for(engine, diagnose, generate)

    assert len(decision.ranked) == 3
    assert all(isinstance(candidate, ScoredCandidate) for candidate in decision.ranked)
    for candidate in decision.ranked:
        assert candidate.prediction.model_version == "deterministic-scorer-v1"
        assert candidate.breakdown.payment_amount == 1_000_000
        assert candidate.risk_level in set(RiskLevel)


def test_candidates_are_ordered_by_descending_expected_value(engine, diagnose, generate):
    """Requirement 11.2."""
    _, decision = decide_for(engine, diagnose, generate)
    values = [candidate.expected_recovery_value for candidate in decision.ranked]
    assert values == sorted(values, reverse=True)


def test_highest_expected_value_candidate_is_selected(engine, diagnose, generate):
    """Requirement 11.3, 25.8."""
    _, decision = decide_for(engine, diagnose, generate)
    best = max(decision.ranked, key=lambda candidate: candidate.expected_recovery_value)
    assert decision.selected_action is best.action
    assert decision.expected_recovery_value == best.expected_recovery_value


def test_bank_timeout_selects_retry_later_over_retry_now(engine, diagnose, generate):
    """The headline behaviour: value beats immediacy."""
    _, decision = decide_for(engine, diagnose, generate, reason=FailureReason.BANK_TIMEOUT)

    assert decision.selected_action is ActionType.RETRY_LATER
    alternatives = {item["action"] for item in decision.explanation.alternatives}
    assert alternatives == {"RETRY_NOW", "SEND_PAYMENT_LINK"}


def test_expired_card_selects_change_payment_method(engine, diagnose, generate):
    """Requirement 25.13 precondition: the instrument must change."""
    _, decision = decide_for(engine, diagnose, generate, reason=FailureReason.EXPIRED_CARD)
    assert decision.selected_action is ActionType.CHANGE_PAYMENT_METHOD


def test_checkout_abandonment_selects_an_engagement_action(engine, diagnose, generate):
    _, decision = decide_for(engine, diagnose, generate, reason=FailureReason.CHECKOUT_ABANDONMENT)
    assert decision.selected_action in {ActionType.SEND_PAYMENT_LINK, ActionType.SEND_REMINDER}


def test_unknown_cause_selects_escalation(engine, diagnose, generate):
    """An unknown cause must not produce an automated financial action."""
    _, decision = decide_for(engine, diagnose, generate, reason=FailureReason.UNKNOWN)
    assert decision.selected_action is ActionType.ESCALATE_HUMAN


def test_decision_reproduces_the_design_walkthrough_figures(engine, diagnose, generate):
    """The numbers quoted in the design's end-to-end example."""
    _, decision = decide_for(engine, diagnose, generate, reason=FailureReason.BANK_TIMEOUT)

    by_action = {
        candidate.action: candidate.expected_recovery_value for candidate in decision.ranked
    }
    assert by_action[ActionType.RETRY_LATER] == 764_000
    assert by_action[ActionType.SEND_PAYMENT_LINK] == 529_000
    assert by_action[ActionType.RETRY_NOW] == 345_500
    assert decision.probability == pytest.approx(0.776)


# ---------------------------------------------------------------------------
# Tie-breaking (Requirement 11.2)
# ---------------------------------------------------------------------------


def test_ties_break_on_probability_then_cost_then_declaration_order(engine, settings):
    """Ranking is a total order, so it never depends on input order."""
    from app.ml.predictor import PredictionResult

    class FlatPredictor:
        """Returns the same probability for every action, forcing near-ties."""

        def predict(self, context, action):
            return PredictionResult(
                probability=0.5,
                confidence=0.9,
                model_version="flat-test",
                features_used=("failure_reason",),
                explanation=(),
            )

    flat_engine = RecoveryDecisionEngine(
        predictor=FlatPredictor(),
        calculator=ExpectedRecoveryCalculator(settings),
        settings=settings,
    )
    context = context_with()
    diagnosis = RuleBasedDiagnosisEngine().diagnose(context)

    candidates = [ActionType.SEND_PAYMENT_LINK, ActionType.RETRY_NOW, ActionType.RETRY_LATER]
    decision = flat_engine.decide(context, diagnosis, candidates)
    reversed_decision = flat_engine.decide(context, diagnosis, list(reversed(candidates)))

    # Equal probabilities, so the cheapest intervention wins: RETRY_NOW (500).
    assert decision.selected_action is ActionType.RETRY_NOW
    assert [c.action for c in decision.ranked] == [c.action for c in reversed_decision.ranked]


def test_ranking_is_stable_across_repeated_calls(engine, diagnose, generate):
    context = context_with()
    diagnosis = diagnose(context)
    candidates = generate(context, diagnosis)

    first = engine.decide(context, diagnosis, candidates)
    second = engine.decide(context, diagnosis, candidates)

    assert [c.action for c in first.ranked] == [c.action for c in second.ranked]
    assert first.expected_recovery_value == second.expected_recovery_value


# ---------------------------------------------------------------------------
# No side effects (Requirement 11.4)
# ---------------------------------------------------------------------------


def test_decide_returns_a_data_structure_only(engine, diagnose, generate):
    """Requirement 11.4, 27.5."""
    _, decision = decide_for(engine, diagnose, generate)
    assert isinstance(decision, RecoveryDecision)


def test_decide_does_not_mutate_the_context(engine, diagnose, generate):
    context = context_with()
    diagnosis = diagnose(context)
    candidates = generate(context, diagnosis)

    before = context.features()
    engine.decide(context, diagnosis, candidates)
    assert context.features() == before


def test_decide_needs_no_database_session(engine, diagnose, generate):
    """The whole decision path is exercisable in memory."""
    _, decision = decide_for(engine, diagnose, generate)
    assert decision.selected_action is not None


def test_decision_engine_exposes_no_execution_method():
    names = {name for name in dir(RecoveryDecisionEngine) if not name.startswith("_")}
    for forbidden in ("execute", "run", "perform", "charge", "retry"):
        assert not any(forbidden in name for name in names), names


# ---------------------------------------------------------------------------
# Risk level
# ---------------------------------------------------------------------------


def test_high_value_payment_raises_the_risk_level(engine, diagnose, generate, settings):
    high_value = replace(
        context_with(), amount=settings.high_value_escalation_threshold + 1
    )
    diagnosis = diagnose(high_value)
    decision = engine.decide(high_value, diagnosis, generate(high_value, diagnosis))

    assert decision.risk_level is RiskLevel.HIGH


def test_terminal_actions_are_low_risk(engine, diagnose, generate):
    _, decision = decide_for(engine, diagnose, generate, reason=FailureReason.UNKNOWN)
    assert decision.risk_level is RiskLevel.LOW


def test_ordinary_retry_is_low_risk(engine, diagnose, generate):
    _, decision = decide_for(engine, diagnose, generate, reason=FailureReason.BANK_TIMEOUT)
    assert decision.risk_level is RiskLevel.LOW


# ---------------------------------------------------------------------------
# Empty candidate list (Requirement 11.5)
# ---------------------------------------------------------------------------


def test_empty_candidates_escalate_when_human_handling_is_permitted(engine, diagnose):
    context = context_with()
    decision = engine.decide(context, diagnose(context), [])

    assert decision.selected_action is ActionType.ESCALATE_HUMAN
    assert decision.ranked == ()
    assert "No candidate recovery action was available" in decision.explanation.reason


def test_empty_candidates_stop_when_escalation_is_disabled(settings, diagnose):
    from app.core.config import Settings

    no_escalation = Settings(_env_file=None, allow_human_escalation=False)
    engine = RecoveryDecisionEngine(
        predictor=DeterministicRecoveryScorer(),
        calculator=ExpectedRecoveryCalculator(no_escalation),
        settings=no_escalation,
    )
    context = context_with()
    decision = engine.decide(context, diagnose(context), [])

    assert decision.selected_action is ActionType.STOP
    assert "not safe" in decision.explanation.reason


# ---------------------------------------------------------------------------
# Explanation (Requirement 12.1-12.3)
# ---------------------------------------------------------------------------


def test_explanation_carries_every_required_field(engine, diagnose, generate):
    """Requirement 12.1."""
    _, decision = decide_for(engine, diagnose, generate)
    payload = decision.explanation.to_dict()

    assert set(payload) == {
        "selected_action",
        "reason",
        "probability",
        "expected_recovery_value",
        "confidence",
        "alternatives",
    }


def test_alternatives_carry_action_probability_and_value(engine, diagnose, generate):
    """Requirement 12.2."""
    _, decision = decide_for(engine, diagnose, generate)

    assert decision.explanation.alternatives
    for alternative in decision.explanation.alternatives:
        assert set(alternative) == {"action", "probability", "expected_recovery_value"}


def test_alternatives_exclude_the_selected_action(engine, diagnose, generate):
    _, decision = decide_for(engine, diagnose, generate)
    actions = {item["action"] for item in decision.explanation.alternatives}
    assert decision.selected_action.value not in actions


def test_reason_names_the_action_and_the_expected_value_basis(engine, diagnose, generate):
    """Requirement 12.3."""
    _, decision = decide_for(engine, diagnose, generate)
    reason = decision.explanation.reason

    assert decision.selected_action.value in reason
    assert "highest expected recovery value" in reason
    assert str(decision.expected_recovery_value) in reason


def test_reason_quantifies_the_margin_over_the_runner_up(engine, diagnose, generate):
    _, decision = decide_for(engine, diagnose, generate)
    assert "beats" in decision.explanation.reason


def test_selected_helper_returns_the_winning_candidate(engine, diagnose, generate):
    _, decision = decide_for(engine, diagnose, generate)
    assert decision.selected is not None
    assert decision.selected.action is decision.selected_action


# ---------------------------------------------------------------------------
# Audit (Requirement 11.6)
# ---------------------------------------------------------------------------


def test_audit_records_evaluation_then_selection(db, clock, engine, diagnose, generate, payment_factory):
    """Requirement 11.6."""
    from app.core.enums import AuditEventType, CaseState
    from app.models import RecoveryCase
    from app.services.audit_service import AuditService

    payment = payment_factory()
    case = RecoveryCase(
        case_id="case_dec_0001",
        payment_id=payment.payment_id,
        state=CaseState.DETECTED,
        amount_at_risk=payment.amount,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    db.add(case)
    db.commit()

    audit = AuditService(session=db, clock=clock)
    context = replace(
        context_with(), case_id=case.case_id, payment_id=payment.payment_id
    )
    diagnosis = diagnose(context)
    decision = engine.decide(
        context, diagnosis, generate(context, diagnosis), audit=audit, workflow_id="wf_dec"
    )
    db.commit()

    assert audit.event_types_for_case(case.case_id) == [
        AuditEventType.RECOVERY_OPTIONS_EVALUATED,
        AuditEventType.RECOVERY_DECISION_SELECTED,
    ]

    events = audit.for_case(case.case_id)
    evaluated, selected = events
    assert evaluated.meta["candidate_count"] == 3
    assert len(evaluated.meta["candidates"]) == 3
    assert selected.meta["selected_action"] == decision.selected_action.value
    assert selected.meta["expected_recovery_value"] == decision.expected_recovery_value
    assert selected.meta["model_version"] == "deterministic-scorer-v1"
    assert selected.meta["alternatives"]
    assert selected.meta["workflow_id"] == "wf_dec"


def test_no_audit_events_when_audit_is_omitted(engine, diagnose, generate):
    """Purity: the decision path is usable without a session."""
    _, decision = decide_for(engine, diagnose, generate)
    assert decision.selected_action is not None


def test_ranking_metadata_shape(engine, diagnose, generate):
    _, decision = decide_for(engine, diagnose, generate)
    rows = decision.ranking_metadata()

    assert len(rows) == 3
    for row in rows:
        assert set(row) == {
            "action",
            "probability",
            "confidence",
            "expected_recovery_value",
            "gross_expected_recovery",
            "intervention_cost",
            "customer_friction_penalty",
            "risk_level",
        }
