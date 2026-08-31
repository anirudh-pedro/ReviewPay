"""Recovery case state machine.

The transition table is the structural guarantee behind the system's central
safety claim: an action cannot reach execution without first passing through
decision and policy stages. ``DETECTED`` leads only to ``DIAGNOSING``, so no
caller — however buggy — can jump a case straight to ``EXECUTING``
(Requirement 16.9).

Terminal states map to the empty set, which makes "no transition out of a terminal
state" a property of the data rather than a check someone must remember to write.
"""

from __future__ import annotations

from app.core.clock import VirtualClock
from app.core.enums import CaseState
from app.core.errors import InvalidStateTransition
from app.core.logging import get_logger
from app.models import RecoveryCase

logger = get_logger("state")

#: Permitted transitions (Requirement 16.2-16.7).
TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.DETECTED: frozenset({CaseState.DIAGNOSING}),
    CaseState.DIAGNOSING: frozenset({CaseState.DIAGNOSED}),
    CaseState.DIAGNOSED: frozenset({CaseState.EVALUATING}),
    CaseState.EVALUATING: frozenset({CaseState.DECISION_READY}),
    CaseState.DECISION_READY: frozenset({CaseState.POLICY_CHECK}),
    CaseState.POLICY_CHECK: frozenset(
        {CaseState.APPROVED, CaseState.BLOCKED, CaseState.ESCALATED}
    ),
    CaseState.APPROVED: frozenset({CaseState.EXECUTING, CaseState.SCHEDULED}),
    CaseState.SCHEDULED: frozenset({CaseState.EXECUTING}),
    CaseState.EXECUTING: frozenset({CaseState.VERIFYING}),
    CaseState.VERIFYING: frozenset({CaseState.RECOVERED, CaseState.FAILED}),
    CaseState.BLOCKED: frozenset({CaseState.STOPPED}),
    # An unrecovered, unblocked case is re-runnable: the next run re-decides with
    # the updated attempt count and recovery history (Requirement 16.7).
    CaseState.FAILED: frozenset({CaseState.DIAGNOSING}),
    # Terminal (Requirement 16.6).
    CaseState.RECOVERED: frozenset(),
    CaseState.ESCALATED: frozenset(),
    CaseState.STOPPED: frozenset(),
}

#: States a case must have passed through before it may execute.
REQUIRED_BEFORE_EXECUTION = (CaseState.DECISION_READY, CaseState.POLICY_CHECK)


class StateMachine:
    """Validates and applies recovery case state transitions."""

    def __init__(self, clock: VirtualClock) -> None:
        self._clock = clock

    def can(self, source: CaseState, target: CaseState) -> bool:
        """True when the transition is permitted."""
        return target in TRANSITIONS.get(source, frozenset())

    def assert_transition(self, source: CaseState, target: CaseState) -> None:
        """Raise ``InvalidStateTransition`` when the transition is not permitted."""
        if not self.can(source, target):
            raise InvalidStateTransition(source, target)

    def transition(self, case: RecoveryCase, target: CaseState) -> RecoveryCase:
        """Move a case to ``target``, stamping the simulation time.

        Leaves the case untouched when the transition is rejected
        (Requirement 16.8).
        """
        source = case.state
        self.assert_transition(source, target)

        case.state = target
        case.updated_at = self._clock.now()

        logger.debug("case %s | %s -> %s", case.case_id, source.value, target.value)
        return case

    def advance(self, case: RecoveryCase, *targets: CaseState) -> RecoveryCase:
        """Apply several transitions in order.

        Convenience for the workflow, which walks a case through short runs of
        bookkeeping states. Each step is validated individually.
        """
        for target in targets:
            self.transition(case, target)
        return case

    @staticmethod
    def is_terminal(state: CaseState) -> bool:
        """True when no transition out of ``state`` is permitted."""
        return not TRANSITIONS.get(state, frozenset())

    @staticmethod
    def reachable_from(state: CaseState) -> frozenset[CaseState]:
        """States directly reachable from ``state``."""
        return TRANSITIONS.get(state, frozenset())
