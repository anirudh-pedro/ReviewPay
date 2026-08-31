"""Policy engine tests (Requirement 13.1-13.12)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.core.config import Settings
from app.core.enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    FailureReason,
    PaymentStatus,
    PolicyOutcome,
)
from app.ml.deterministic_scorer import DeterministicRecoveryScorer
from app.services.candidate_generator import RecoveryActionCandidateGenerator
from app.services.decision_engine import RecoveryDecisionEngine
from app.services.diagnosis_engine import RuleBasedDiagnosisEngine
from app.services.expected_value import ExpectedRecoveryCalculator
from app.services.policy_engine import PolicyEngine
from app.services.policy_rules import RULE_ORDER, PolicyInput, PolicyResult
from tests.test_predictor import context_with


@pytest.fixture
def policy(settings) -> PolicyEngine:
    return PolicyEngine(settings=settings)


@pytest.fixture
def decide(settings):
    """Produce a real decision for a context, so verdicts are tested end to end."""
    engine = RecoveryDecisionEngine(
        predictor=DeterministicRecoveryScorer(),
        calculator=ExpectedRecoveryCalculator(settings),
        settings=settings,
    )
    diagnoser = RuleBasedDiagnosisEngine()
    generator = RecoveryActionCandidateGenerator()

    def _decide(context, forced_action: ActionType | None = None):
        diagnosis = diagnoser.diagnose(context)
        candidates = (
            [forced_action] if forced_action else generator.generate(context, diagnosis)
        )
        return engine.decide(context, diagnosis, candidates)

    return _decide


# ---------------------------------------------------------------------------
# Totality and ordering
# ---------------------------------------------------------------------------


def test_evaluation_always_returns_one_of_three_outcomes(policy, decide):
    """Requirement 13.1."""
    for reason in FailureReason:
        context = context_with(reason=reason)
        result = policy.evaluate(context, decide(context))

        assert isinstance(result, PolicyResult)
        assert result.outcome in set(PolicyOutcome)
        assert result.rule_id
        assert result.reason


def test_rule_order_is_documented_and_stable(policy):
    """Requirement 13.12."""
    assert policy.rule_ids == (
        "invalid_payment_state",
        "unsupported_action",
        "retry_limit_reached",
        "recovery_budget_exhausted",
        "repeated_failure_limit",
        "unknown_failure",
        "high_value_transaction",
    )
    assert RULE_ORDER[-1] == "default_approve"


def test_blocking_rules_precede_escalation_rules(policy):
    """A case that has exhausted retries should stop, not page a human."""
    ids = policy.rule_ids
    assert ids.index("retry_limit_reached") < ids.index("high_value_transaction")
    assert ids.index("repeated_failure_limit") < ids.index("unknown_failure")


def test_retry_rule_precedes_the_budget_rule(policy):
    """A blocked retry keeps its more specific attribution."""
    ids = policy.rule_ids
    assert ids.index("retry_limit_reached") < ids.index("recovery_budget_exhausted")


def test_first_matching_rule_wins(policy, decide, settings):
    """Requirement 13.12: a high-value payment past its retry limit stops."""
    context = context_with(attempt_count=settings.max_automatic_retries)
    context = replace(context, amount=settings.high_value_escalation_threshold + 1)

    result = policy.evaluate(context, decide(context, ActionType.RETRY_LATER))

    assert result.outcome is PolicyOutcome.BLOCKED
    assert result.rule_id == "retry_limit_reached"


# ---------------------------------------------------------------------------
# Approval (Requirement 13.1)
# ---------------------------------------------------------------------------


def test_ordinary_case_is_approved(policy, decide):
    context = context_with(reason=FailureReason.BANK_TIMEOUT, attempt_count=1)
    result = policy.evaluate(context, decide(context))

    assert result.outcome is PolicyOutcome.APPROVED
    assert result.rule_id == "default_approve"
    assert result.approved is True


def test_approval_reason_states_the_limits_checked(policy, decide):
    context = context_with(attempt_count=1)
    reason = policy.evaluate(context, decide(context)).reason

    assert "retries used" in reason
    assert "within the automatic threshold" in reason


# ---------------------------------------------------------------------------
# Retry limit (Requirement 13.3)
# ---------------------------------------------------------------------------


def test_retry_limit_blocks_at_the_configured_maximum(policy, decide, settings):
    """Requirement 13.3: default maximum is 2."""
    assert settings.max_automatic_retries == 2
    context = context_with(attempt_count=2)

    result = policy.evaluate(context, decide(context, ActionType.RETRY_LATER))

    assert result.outcome is PolicyOutcome.BLOCKED
    assert result.rule_id == "retry_limit_reached"
    assert "maximum of 2" in result.reason


def test_retry_limit_permits_the_attempt_below_the_limit(policy, decide):
    context = context_with(attempt_count=1)
    result = policy.evaluate(context, decide(context, ActionType.RETRY_LATER))
    assert result.outcome is PolicyOutcome.APPROVED


def test_retry_limit_blocks_beyond_the_limit(policy, decide):
    context = context_with(attempt_count=7)
    result = policy.evaluate(context, decide(context, ActionType.RETRY_NOW))
    assert result.outcome is PolicyOutcome.BLOCKED
    assert result.rule_id == "retry_limit_reached"


def test_retry_limit_does_not_block_a_non_retry_action(policy, decide):
    """A reminder does not consume a payment attempt."""
    context = context_with(reason=FailureReason.CHECKOUT_ABANDONMENT, attempt_count=5)
    result = policy.evaluate(context, decide(context, ActionType.SEND_REMINDER))
    assert result.rule_id != "retry_limit_reached"


def test_retry_limit_is_configurable(decide):
    generous = Settings(_env_file=None, max_automatic_retries=5)
    engine = PolicyEngine(settings=generous)
    context = context_with(attempt_count=3)

    assert engine.evaluate(context, decide(context, ActionType.RETRY_LATER)).outcome is (
        PolicyOutcome.APPROVED
    )


# ---------------------------------------------------------------------------
# High value (Requirement 13.4)
# ---------------------------------------------------------------------------


def test_high_value_payment_escalates(policy, decide, settings):
    """Requirement 13.4."""
    context = replace(
        context_with(attempt_count=1), amount=settings.high_value_escalation_threshold + 1
    )
    result = policy.evaluate(context, decide(context, ActionType.RETRY_LATER))

    assert result.outcome is PolicyOutcome.ESCALATED
    assert result.rule_id == "high_value_transaction"
    assert result.escalated is True
    assert "exceeds the automatic recovery threshold" in result.reason


def test_payment_at_the_threshold_is_not_escalated(policy, decide, settings):
    """The threshold is inclusive of automatic handling."""
    context = replace(
        context_with(attempt_count=1), amount=settings.high_value_escalation_threshold
    )
    assert policy.evaluate(context, decide(context, ActionType.RETRY_LATER)).outcome is (
        PolicyOutcome.APPROVED
    )


def test_high_value_blocks_when_escalation_is_disabled(decide, settings):
    strict = Settings(
        _env_file=None,
        allow_human_escalation=False,
        high_value_escalation_threshold=settings.high_value_escalation_threshold,
    )
    engine = PolicyEngine(settings=strict)
    context = replace(
        context_with(attempt_count=1), amount=strict.high_value_escalation_threshold + 1
    )

    result = engine.evaluate(context, decide(context, ActionType.RETRY_LATER))
    assert result.outcome is PolicyOutcome.BLOCKED
    assert result.rule_id == "high_value_transaction"


# ---------------------------------------------------------------------------
# Unknown failure (Requirement 13.5)
# ---------------------------------------------------------------------------


def test_unknown_failure_escalates(policy, decide):
    """Requirement 13.5."""
    context = context_with(reason=FailureReason.UNKNOWN, attempt_count=1)
    result = policy.evaluate(context, decide(context))

    assert result.outcome is PolicyOutcome.ESCALATED
    assert result.rule_id == "unknown_failure"


def test_unknown_failure_blocks_when_escalation_is_disabled(decide):
    strict = Settings(_env_file=None, allow_human_escalation=False)
    engine = PolicyEngine(settings=strict)
    context = context_with(reason=FailureReason.UNKNOWN, attempt_count=1)

    result = engine.evaluate(context, decide(context, ActionType.ESCALATE_HUMAN))
    assert result.outcome is PolicyOutcome.BLOCKED
    assert result.rule_id == "unknown_failure"


# ---------------------------------------------------------------------------
# Invalid payment state (Requirement 13.6)
# ---------------------------------------------------------------------------


def test_recovering_a_successful_payment_is_blocked(policy, decide):
    """Requirement 13.6: prevents double-charging."""
    context = replace(context_with(attempt_count=1), payment_status=PaymentStatus.SUCCEEDED)
    result = policy.evaluate(context, decide(context, ActionType.RETRY_LATER))

    assert result.outcome is PolicyOutcome.BLOCKED
    assert result.rule_id == "invalid_payment_state"
    assert "SUCCEEDED" in result.reason


def test_terminal_actions_are_valid_from_any_state(policy, decide):
    """Escalating or stopping moves no money, so state does not gate it."""
    context = replace(context_with(attempt_count=1), payment_status=PaymentStatus.SUCCEEDED)
    result = policy.evaluate(context, decide(context, ActionType.STOP))
    assert result.rule_id != "invalid_payment_state"


def test_abandoned_payment_may_be_recovered(policy, decide):
    context = replace(
        context_with(reason=FailureReason.CHECKOUT_ABANDONMENT, attempt_count=1),
        payment_status=PaymentStatus.ABANDONED,
    )
    result = policy.evaluate(context, decide(context, ActionType.SEND_REMINDER))
    assert result.outcome is PolicyOutcome.APPROVED


# ---------------------------------------------------------------------------
# Unsupported action (Requirement 13.7)
# ---------------------------------------------------------------------------


def test_unsupported_action_is_blocked(settings, decide):
    """Requirement 13.7."""
    engine = PolicyEngine(
        settings=settings,
        supported_actions=frozenset({ActionType.RETRY_NOW, ActionType.STOP}),
    )
    context = context_with(attempt_count=1)

    result = engine.evaluate(context, decide(context, ActionType.RETRY_LATER))
    assert result.outcome is PolicyOutcome.BLOCKED
    assert result.rule_id == "unsupported_action"
    assert "RETRY_LATER" in result.reason


def test_supported_action_passes_the_support_check(settings, decide):
    engine = PolicyEngine(
        settings=settings, supported_actions=frozenset({ActionType.RETRY_LATER})
    )
    context = context_with(attempt_count=1)
    assert engine.evaluate(context, decide(context, ActionType.RETRY_LATER)).outcome is (
        PolicyOutcome.APPROVED
    )


# ---------------------------------------------------------------------------
# Repeated failure (Requirement 13.8)
# ---------------------------------------------------------------------------


def test_repeated_failure_limit_blocks(policy, decide, settings):
    """Requirement 13.8: the guarantee that a case terminates."""
    context = replace(
        context_with(reason=FailureReason.CHECKOUT_ABANDONMENT, attempt_count=0),
        unsuccessful_outcome_count=settings.repeated_failure_limit,
    )
    result = policy.evaluate(context, decide(context, ActionType.SEND_REMINDER))

    assert result.outcome is PolicyOutcome.BLOCKED
    assert result.rule_id == "repeated_failure_limit"
    assert "limit of 3" in result.reason


def test_repeated_failure_below_the_limit_is_permitted(policy, decide):
    context = replace(
        context_with(reason=FailureReason.CHECKOUT_ABANDONMENT, attempt_count=0),
        unsuccessful_outcome_count=1,
    )
    assert policy.evaluate(context, decide(context, ActionType.SEND_REMINDER)).outcome is (
        PolicyOutcome.APPROVED
    )


# ---------------------------------------------------------------------------
# Persistence and audit (Requirement 13.10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "expected_status", "expected_event"),
    [
        (PolicyOutcome.APPROVED, ActionStatus.APPROVED, AuditEventType.POLICY_APPROVED),
        (PolicyOutcome.BLOCKED, ActionStatus.BLOCKED, AuditEventType.POLICY_BLOCKED),
        (PolicyOutcome.ESCALATED, ActionStatus.ESCALATED, AuditEventType.POLICY_ESCALATED),
    ],
)
def test_verdict_is_persisted_and_audited(
    db, clock, policy, decide, payment_factory, outcome, expected_status, expected_event
):
    """Requirement 13.10."""
    from app.core.enums import CaseState, RiskLevel
    from app.models import RecoveryAction, RecoveryCase
    from app.services.audit_service import AuditService

    payment = payment_factory(status=PaymentStatus.FAILED, failure_reason=FailureReason.BANK_TIMEOUT)
    now = clock.now()
    case = RecoveryCase(
        case_id=f"case_pol_{outcome.value}",
        payment_id=payment.payment_id,
        state=CaseState.POLICY_CHECK,
        amount_at_risk=payment.amount,
        created_at=now,
        updated_at=now,
    )
    db.add(case)
    db.commit()

    context = replace(
        context_with(attempt_count=1), case_id=case.case_id, payment_id=payment.payment_id
    )
    decision = decide(context)

    action = RecoveryAction(
        action_id=f"act_pol_{outcome.value}",
        case_id=case.case_id,
        payment_id=payment.payment_id,
        action_type=decision.selected_action,
        estimated_probability=decision.probability,
        confidence=decision.confidence,
        model_version=decision.model_version,
        expected_recovery_value=decision.expected_recovery_value,
        erv_breakdown=decision.breakdown.to_dict(),
        risk_level=RiskLevel.LOW,
        decision_explanation=decision.explanation.to_dict(),
        created_at=now,
    )
    db.add(action)
    db.commit()

    result = PolicyResult(outcome=outcome, rule_id="test_rule", reason="test reason")
    policy.apply_to_action(action, result)

    audit = AuditService(session=db, clock=clock)
    policy.audit(audit, context, decision, result, workflow_id="wf_pol")
    db.commit()

    assert action.policy_outcome is outcome
    assert action.policy_rule_id == "test_rule"
    assert action.policy_reason == "test reason"
    assert action.status is expected_status

    events = audit.for_case(case.case_id)
    assert [event.event_type for event in events] == [expected_event]

    metadata = events[0].meta
    assert metadata["policy_outcome"] == outcome.value
    assert metadata["policy_rule_id"] == "test_rule"
    assert metadata["policy_reason"] == "test reason"
    assert metadata["evaluated_action"] == decision.selected_action.value
    assert metadata["workflow_id"] == "wf_pol"
    assert metadata["limits"]["max_automatic_retries"] == 2
    assert metadata["rules_evaluated"] == list(policy.rule_ids)


def test_escalated_action_requires_human_approval_flag(db, clock, policy, payment_factory):
    from app.core.enums import CaseState, RiskLevel
    from app.models import RecoveryAction, RecoveryCase

    payment = payment_factory(status=PaymentStatus.FAILED)
    now = clock.now()
    case = RecoveryCase(
        case_id="case_pol_flag",
        payment_id=payment.payment_id,
        state=CaseState.POLICY_CHECK,
        amount_at_risk=payment.amount,
        created_at=now,
        updated_at=now,
    )
    db.add(case)
    action = RecoveryAction(
        action_id="act_pol_flag",
        case_id=case.case_id,
        payment_id=payment.payment_id,
        action_type=ActionType.RETRY_LATER,
        estimated_probability=0.5,
        confidence=1.0,
        model_version="test",
        expected_recovery_value=1,
        erv_breakdown={},
        risk_level=RiskLevel.HIGH,
        decision_explanation={},
        created_at=now,
    )
    db.add(action)
    db.commit()

    policy.apply_to_action(
        action,
        PolicyResult(
            outcome=PolicyOutcome.ESCALATED, rule_id="high_value_transaction", reason="big"
        ),
    )
    assert action.requires_human_approval is True


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_engine_exposes_no_execution_method():
    """Requirement 13.9: the gate does not act, it only permits."""
    names = {name for name in dir(PolicyEngine) if not name.startswith("_")}
    for forbidden in ("execute", "perform", "charge", "retry", "run"):
        assert not any(forbidden in name for name in names), names


def test_rules_are_injectable(settings, decide):
    """Requirement 13.11: the rule set is configuration, not hard-wiring."""

    class AlwaysBlock:
        rule_id = "always_block"

        def evaluate(self, data: PolicyInput) -> PolicyResult:
            return PolicyResult(
                outcome=PolicyOutcome.BLOCKED, rule_id=self.rule_id, reason="blocked by test"
            )

    engine = PolicyEngine(settings=settings, rules=(AlwaysBlock(),))
    context = context_with(attempt_count=1)

    result = engine.evaluate(context, decide(context))
    assert result.rule_id == "always_block"


def test_empty_rule_set_falls_through_to_approval(settings, decide):
    engine = PolicyEngine(settings=settings, rules=())
    context = context_with(attempt_count=1)
    assert engine.evaluate(context, decide(context)).rule_id == "default_approve"


def test_policy_result_serialises(policy, decide):
    context = context_with(attempt_count=1)
    payload = policy.evaluate(context, decide(context)).to_dict()
    assert set(payload) == {"outcome", "rule_id", "reason"}
