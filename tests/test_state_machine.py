"""State machine tests (Requirement 16.1-16.10)."""

from __future__ import annotations

import pytest

from app.core.enums import CaseState
from app.core.errors import InvalidStateTransition
from app.models import RecoveryCase
from app.services.state_machine import TRANSITIONS, StateMachine


@pytest.fixture
def machine(clock) -> StateMachine:
    return StateMachine(clock)


@pytest.fixture
def case(db, payment_factory, clock) -> RecoveryCase:
    payment = payment_factory()
    now = clock.now()
    record = RecoveryCase(
        case_id="case_sm_0001",
        payment_id=payment.payment_id,
        state=CaseState.DETECTED,
        amount_at_risk=payment.amount,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.commit()
    return record


# ---------------------------------------------------------------------------
# Table shape
# ---------------------------------------------------------------------------


def test_every_state_appears_in_the_transition_table():
    """Requirement 16.1: all fifteen states are accounted for."""
    assert set(TRANSITIONS) == set(CaseState)
    assert len(TRANSITIONS) == 15


def test_terminal_states_have_no_outgoing_transitions():
    """Requirement 16.6."""
    for state in CaseState.terminal():
        assert TRANSITIONS[state] == frozenset()


def test_no_awaiting_approval_state_in_phase_zero():
    assert "AWAITING_APPROVAL" not in {state.value for state in TRANSITIONS}


# ---------------------------------------------------------------------------
# Forward path
# ---------------------------------------------------------------------------


def test_full_forward_path_is_permitted(machine, case):
    """Requirement 16.2."""
    path = [
        CaseState.DIAGNOSING,
        CaseState.DIAGNOSED,
        CaseState.EVALUATING,
        CaseState.DECISION_READY,
        CaseState.POLICY_CHECK,
        CaseState.APPROVED,
        CaseState.EXECUTING,
        CaseState.VERIFYING,
        CaseState.RECOVERED,
    ]
    for target in path:
        machine.transition(case, target)
    assert case.state is CaseState.RECOVERED


def test_policy_check_may_block_or_escalate(machine):
    """Requirement 16.3."""
    assert machine.can(CaseState.POLICY_CHECK, CaseState.BLOCKED)
    assert machine.can(CaseState.POLICY_CHECK, CaseState.ESCALATED)
    assert machine.can(CaseState.POLICY_CHECK, CaseState.APPROVED)


def test_blocked_leads_to_stopped(machine):
    """Requirement 16.3."""
    assert machine.can(CaseState.BLOCKED, CaseState.STOPPED)


def test_approved_may_schedule_or_execute(machine):
    """Requirement 16.4."""
    assert machine.can(CaseState.APPROVED, CaseState.SCHEDULED)
    assert machine.can(CaseState.APPROVED, CaseState.EXECUTING)


def test_scheduled_leads_to_executing(machine):
    """Requirement 16.4: the retry becomes due once the clock reaches it."""
    assert machine.can(CaseState.SCHEDULED, CaseState.EXECUTING)


def test_verifying_may_recover_or_fail(machine):
    """Requirement 16.5."""
    assert machine.can(CaseState.VERIFYING, CaseState.RECOVERED)
    assert machine.can(CaseState.VERIFYING, CaseState.FAILED)


def test_failed_is_re_runnable(machine):
    """Requirement 16.7."""
    assert machine.can(CaseState.FAILED, CaseState.DIAGNOSING)
    assert machine.is_terminal(CaseState.FAILED) is False


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


def test_detected_cannot_jump_straight_to_executing(machine, case):
    """Requirement 16.9, 25.10: the central safety guarantee."""
    with pytest.raises(InvalidStateTransition) as excinfo:
        machine.transition(case, CaseState.EXECUTING)

    message = str(excinfo.value)
    assert "DETECTED" in message
    assert "EXECUTING" in message
    # The case is left untouched (Requirement 16.8).
    assert case.state is CaseState.DETECTED


def test_execution_is_unreachable_without_decision_and_policy(machine):
    """Requirement 16.9: every path into EXECUTING passes the required stages."""
    predecessors = {
        source for source, targets in TRANSITIONS.items() if CaseState.EXECUTING in targets
    }
    assert predecessors == {CaseState.APPROVED, CaseState.SCHEDULED}

    # APPROVED and SCHEDULED are themselves only reachable via POLICY_CHECK,
    # which is only reachable via DECISION_READY.
    approved_predecessors = {
        source for source, targets in TRANSITIONS.items() if CaseState.APPROVED in targets
    }
    assert approved_predecessors == {CaseState.POLICY_CHECK}

    policy_predecessors = {
        source for source, targets in TRANSITIONS.items() if CaseState.POLICY_CHECK in targets
    }
    assert policy_predecessors == {CaseState.DECISION_READY}


def test_no_transition_out_of_a_terminal_state(machine, case):
    """Requirement 16.6."""
    case.state = CaseState.RECOVERED
    for target in CaseState:
        with pytest.raises(InvalidStateTransition):
            machine.transition(case, target)
    assert case.state is CaseState.RECOVERED


def test_skipping_diagnosis_is_rejected(machine, case):
    with pytest.raises(InvalidStateTransition):
        machine.transition(case, CaseState.DECISION_READY)


def test_policy_check_cannot_reach_executing_directly(machine):
    """Approval must be recorded before execution."""
    assert not machine.can(CaseState.POLICY_CHECK, CaseState.EXECUTING)


# ---------------------------------------------------------------------------
# Bookkeeping
# ---------------------------------------------------------------------------


def test_transition_stamps_the_simulation_time(machine, case, clock):
    """Requirement 16.10."""
    clock.advance(minutes=30)
    machine.transition(case, CaseState.DIAGNOSING)
    assert case.updated_at == clock.now()


def test_advance_applies_several_transitions(machine, case):
    machine.advance(case, CaseState.DIAGNOSING, CaseState.DIAGNOSED, CaseState.EVALUATING)
    assert case.state is CaseState.EVALUATING


def test_advance_rejects_an_invalid_step_and_stops_there(machine, case):
    with pytest.raises(InvalidStateTransition):
        machine.advance(case, CaseState.DIAGNOSING, CaseState.EXECUTING)
    # The first step applied; the invalid second step did not.
    assert case.state is CaseState.DIAGNOSING


def test_reachable_from_reports_the_table(machine):
    assert machine.reachable_from(CaseState.DETECTED) == frozenset({CaseState.DIAGNOSING})
    assert machine.reachable_from(CaseState.RECOVERED) == frozenset()
