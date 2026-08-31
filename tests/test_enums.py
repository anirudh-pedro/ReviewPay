"""Enumeration membership tests (Requirement 3.1-3.4, 19.1)."""

from app.core.enums import (
    ActionType,
    AuditEventType,
    CaseState,
    FailureReason,
    PolicyOutcome,
)


def test_failure_reason_has_exactly_seven_members():
    assert len(FailureReason) == 7


def test_failure_reason_uses_network_error_not_network_failure():
    """Requirement 3.2: the member is NETWORK_ERROR."""
    assert FailureReason.NETWORK_ERROR.value == "NETWORK_ERROR"
    assert not hasattr(FailureReason, "NETWORK_FAILURE")
    assert "NETWORK_FAILURE" not in {member.value for member in FailureReason}


def test_failure_reason_members():
    assert {member.value for member in FailureReason} == {
        "BANK_TIMEOUT",
        "INSUFFICIENT_FUNDS",
        "EXPIRED_CARD",
        "NETWORK_ERROR",
        "CHECKOUT_ABANDONMENT",
        "SUBSCRIPTION_FAILURE",
        "UNKNOWN",
    }


def test_action_type_has_exactly_seven_members():
    assert len(ActionType) == 7


def test_action_type_members():
    assert {member.value for member in ActionType} == {
        "RETRY_NOW",
        "RETRY_LATER",
        "SEND_PAYMENT_LINK",
        "CHANGE_PAYMENT_METHOD",
        "SEND_REMINDER",
        "ESCALATE_HUMAN",
        "STOP",
    }


def test_policy_outcome_has_exactly_three_members():
    """Requirement 3.4: APPROVED, BLOCKED, ESCALATED only."""
    assert len(PolicyOutcome) == 3
    assert {member.value for member in PolicyOutcome} == {
        "APPROVED",
        "BLOCKED",
        "ESCALATED",
    }


def test_audit_event_type_has_exactly_thirteen_members():
    """Requirement 19.1: exactly thirteen event types."""
    assert len(AuditEventType) == 13


def test_audit_event_type_members():
    assert {member.value for member in AuditEventType} == {
        "REVENUE_RISK_DETECTED",
        "DIAGNOSIS_COMPLETED",
        "RECOVERY_OPTIONS_EVALUATED",
        "RECOVERY_DECISION_SELECTED",
        "POLICY_APPROVED",
        "POLICY_BLOCKED",
        "POLICY_ESCALATED",
        "ACTION_SCHEDULED",
        "ACTION_EXECUTED",
        "ACTION_FAILED",
        "OUTCOME_VERIFIED",
        "REVENUE_RECOVERED",
        "WORKFLOW_STOPPED",
    }


def test_audit_event_type_excludes_phase_one_events():
    """Phase 1 intelligence events are not part of Phase 0."""
    deferred = {
        "RECOVERY_FINGERPRINT_CREATED",
        "RECOVERY_CONTEXT_BUILT",
        "CANDIDATE_ACTIONS_GENERATED",
        "RECOVERY_PROBABILITY_PREDICTED",
        "EXPECTED_VALUE_CALCULATED",
        "RECOVERY_ACTIONS_RANKED",
        "RECOVERY_STRATEGY_SELECTED",
        "POLICY_APPROVAL_REQUIRED",
    }
    assert deferred.isdisjoint({member.value for member in AuditEventType})


def test_case_state_has_exactly_fifteen_members():
    """Requirement 16.1: fifteen states, and no AWAITING_APPROVAL in Phase 0."""
    assert len(CaseState) == 15
    assert "AWAITING_APPROVAL" not in {member.value for member in CaseState}


def test_case_state_terminal_set():
    """Requirement 16.6."""
    assert CaseState.terminal() == frozenset(
        {CaseState.RECOVERED, CaseState.ESCALATED, CaseState.STOPPED}
    )


def test_retry_actions_consume_attempts():
    assert ActionType.RETRY_NOW in ActionType.retry_actions()
    assert ActionType.RETRY_LATER in ActionType.retry_actions()
    assert ActionType.SEND_REMINDER not in ActionType.retry_actions()


def test_enums_serialize_as_strings():
    """Stable database and JSON representations."""
    assert FailureReason.BANK_TIMEOUT == "BANK_TIMEOUT"
    assert ActionType.RETRY_LATER == "RETRY_LATER"
