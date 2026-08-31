"""Action execution interface.

The **only** component permitted to change payment state. Everything upstream —
scoring, valuation, ranking, policy — returns data structures; this is where a
decision becomes an act (Requirement 27.5).

Provider-independent by construction. Phase 1 adds a ``RazorpayTestExecutor``
implementing this Protocol and registers it in the container; the decision engine,
policy engine, and workflow are untouched (Requirement 14.11).

``schedule()`` sits alongside ``execute()`` because deferring an action is
provider behaviour, not orchestration behaviour: a real provider may hold a
mandate, a simulator merely records a due time. Keeping both here means the
workflow never needs to know which kind of executor it has.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.core.enums import ActionType, ExecutionStatus
from app.services.context_builder import RecoveryContext


@dataclass(frozen=True)
class ExecutionResult:
    """What the executor did, and what the provider said.

    Never treated as proof of recovery. The outcome verifier re-reads persisted
    payment state to decide that (Requirement 15.2), which is what stops a buggy or
    optimistic executor from inflating reported revenue.
    """

    action: ActionType
    status: ExecutionStatus
    provider_response: dict[str, Any]
    executed_at: datetime

    @property
    def reported_success(self) -> bool:
        """What the executor *claims*. Not the same as recovery."""
        return self.status is ExecutionStatus.SUCCEEDED

    @property
    def attempted_charge(self) -> bool:
        """Whether this execution actually tried to move money."""
        return self.status in {ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED}

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "status": self.status.value,
            "provider_response": self.provider_response,
            "executed_at": self.executed_at.isoformat(),
        }


@runtime_checkable
class ActionExecutor(Protocol):
    """Performs recovery actions against a payment provider."""

    def supports(self, action: ActionType) -> bool:
        """Whether this executor can perform the action."""
        ...

    @property
    def supported_actions(self) -> frozenset[ActionType]:
        """Every action this executor can perform.

        The policy engine uses this to block an unsupported action before it is
        attempted (Requirement 13.7).
        """
        ...

    def execute(self, action: ActionType, context: RecoveryContext) -> ExecutionResult:
        """Perform the action now (Requirement 14.1)."""
        ...

    def schedule(
        self, action: ActionType, context: RecoveryContext, scheduled_at: datetime
    ) -> ExecutionResult:
        """Defer the action until ``scheduled_at`` without touching the payment."""
        ...


__all__ = ["ActionExecutor", "ExecutionResult"]
