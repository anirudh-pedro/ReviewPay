"""Deterministic payment simulator.

The only ``ActionExecutor`` in Phase 0. **No real money moves and no external
provider is contacted** (Requirement 14.2).

Outcomes are decided in two layers:

1. **A scripted table** pins the behaviours the specification requires, so the
   headline demo scenarios are guaranteed rather than probable. A bank timeout
   recovers on a delayed retry; an expired card refuses a plain retry and accepts a
   new instrument; insufficient funds refuses retries until the budget is spent.

2. **A seeded hash draw** decides everything else. ``sha256(seed, payment_id,
   action, attempt)`` maps to a value in ``[0, 1)`` and is compared against a
   configured per-scenario probability. Because the inputs are stable identifiers
   rather than a mutable RNG stream, the same case yields the same outcome on every
   machine, in any order, however many times it runs (Requirement 14.8).

That second point is the reason this is a hash and not ``random.Random(seed)``: a
shared RNG would make one case's outcome depend on how many other cases ran first,
which would make a live demo unrepeatable.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Any

from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings, get_settings
from app.core.enums import (
    ActionType,
    AuditEventType,
    ExecutionStatus,
    FailureReason,
    PaymentStatus,
    WorkflowStage,
)
from app.core.errors import RecordNotFound
from app.core.logging import get_logger
from app.integrations.action_executor import ExecutionResult
from app.models import Payment
from app.services.audit_service import AuditService
from app.services.context_builder import RecoveryContext
from app.services.payment_service import PaymentService

logger = get_logger("simulator")


class ScriptedOutcome(str, Enum):
    """A forced outcome for a (failure reason, action) pair."""

    ALWAYS_SUCCEED = "ALWAYS_SUCCEED"
    ALWAYS_FAIL = "ALWAYS_FAIL"


#: Scripted outcomes required by the specification (Requirement 14.5-14.7).
SCRIPTED_OUTCOMES: dict[tuple[FailureReason, ActionType], ScriptedOutcome] = {
    # Requirement 14.5: a transient bank fault clears, so the delayed retry works.
    (FailureReason.BANK_TIMEOUT, ActionType.RETRY_LATER): ScriptedOutcome.ALWAYS_SUCCEED,
    # Requirement 14.6: retrying a dead card cannot work; a new instrument can.
    (FailureReason.EXPIRED_CARD, ActionType.RETRY_NOW): ScriptedOutcome.ALWAYS_FAIL,
    (FailureReason.EXPIRED_CARD, ActionType.RETRY_LATER): ScriptedOutcome.ALWAYS_FAIL,
    (
        FailureReason.EXPIRED_CARD,
        ActionType.CHANGE_PAYMENT_METHOD,
    ): ScriptedOutcome.ALWAYS_SUCCEED,
    # Requirement 14.7: retries against an empty balance keep failing until the
    # retry budget is exhausted.
    (FailureReason.INSUFFICIENT_FUNDS, ActionType.RETRY_NOW): ScriptedOutcome.ALWAYS_FAIL,
    (FailureReason.INSUFFICIENT_FUNDS, ActionType.RETRY_LATER): ScriptedOutcome.ALWAYS_FAIL,
}

#: Actions that attempt to move money.
_CHARGE_ACTIONS = frozenset(
    {ActionType.RETRY_NOW, ActionType.RETRY_LATER, ActionType.CHANGE_PAYMENT_METHOD}
)

#: Actions that recover through a customer-facing channel rather than a direct charge.
_CHANNEL_ACTIONS = frozenset({ActionType.SEND_PAYMENT_LINK, ActionType.SEND_REMINDER})

#: Actions that end the workflow without attempting anything.
_TERMINAL_ACTIONS = frozenset({ActionType.ESCALATE_HUMAN, ActionType.STOP})

_TERMINAL_STATUS = {
    ActionType.ESCALATE_HUMAN: ExecutionStatus.ESCALATED,
    ActionType.STOP: ExecutionStatus.STOPPED,
}


def outcome_draw(seed: int, payment_id: str, action: ActionType, attempt: int) -> float:
    """Deterministic pseudo-random value in ``[0, 1)`` for one execution.

    Derived from stable identifiers, so it is reproducible across processes,
    machines, and execution orders (Requirement 14.8).
    """
    material = f"{seed}:{payment_id}:{action.value}:{attempt}".encode()
    return int.from_bytes(sha256(material).digest()[:8], "big") / 2**64


class PaymentSimulatorExecutor:
    """Simulates payment provider behaviour without moving real money."""

    provider = "payment_simulator"

    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        clock: VirtualClock | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        if clock is None:
            from app.core.container import get_clock

            clock = get_clock(self._settings)
        self._clock = clock
        self._payments = PaymentService(session, clock)

    # -- capability --------------------------------------------------------

    @property
    def supported_actions(self) -> frozenset[ActionType]:
        """The simulator implements every action type (Requirement 14.3)."""
        return frozenset(ActionType)

    def supports(self, action: ActionType) -> bool:
        return action in self.supported_actions

    # -- deferral ----------------------------------------------------------

    def schedule(
        self, action: ActionType, context: RecoveryContext, scheduled_at: datetime
    ) -> ExecutionResult:
        """Record a deferred action without attempting a charge.

        The "delayed retry" behaviour (Requirement 14.3): nothing happens to the
        payment now, and the retry becomes due when the virtual clock reaches
        ``scheduled_at``.
        """
        return ExecutionResult(
            action=action,
            status=ExecutionStatus.SCHEDULED,
            provider_response={
                "simulated": True,
                "provider": self.provider,
                "outcome": "scheduled",
                "scheduled_at": scheduled_at.isoformat(),
                "note": (
                    "No charge attempted. The retry becomes due when simulation time "
                    "reaches scheduled_at."
                ),
            },
            executed_at=self._clock.now(),
        )

    # -- execution ---------------------------------------------------------

    def execute(
        self,
        action: ActionType,
        context: RecoveryContext,
        *,
        audit: AuditService | None = None,
        workflow_id: str | None = None,
    ) -> ExecutionResult:
        """Perform the action and return what the simulated provider reported.

        ``audit`` is optional so the simulator can be exercised in isolation; the
        workflow always supplies it (Requirement 14.12).
        """
        if action in _TERMINAL_ACTIONS:
            result = self._terminal(action, context)
        else:
            result = self._attempt(action, context)

        if audit is not None:
            self._audit(audit, context, result, workflow_id)

        logger.info(
            "execute | %s | %s -> %s",
            context.payment_id,
            action.value,
            result.status.value,
        )
        return result

    # -- behaviours --------------------------------------------------------

    def _terminal(self, action: ActionType, context: RecoveryContext) -> ExecutionResult:
        """Escalation and stopped-action behaviours (Requirement 14.3)."""
        return ExecutionResult(
            action=action,
            status=_TERMINAL_STATUS[action],
            provider_response={
                "simulated": True,
                "provider": self.provider,
                "outcome": _TERMINAL_STATUS[action].value.lower(),
                "payment_touched": False,
                "note": (
                    "Handed to a human; no charge attempted."
                    if action is ActionType.ESCALATE_HUMAN
                    else "Workflow stopped; no charge attempted."
                ),
            },
            executed_at=self._clock.now(),
        )

    def _attempt(self, action: ActionType, context: RecoveryContext) -> ExecutionResult:
        """Charge and channel behaviours (Requirement 14.3, 14.10)."""
        payment = self._session.get(Payment, context.payment_id)
        if payment is None:
            raise RecordNotFound("Payment", context.payment_id)

        reason = context.failure_reason
        attempt_number = payment.attempt_count + 1

        succeeded, basis = self._decide_outcome(reason, action, payment.payment_id, attempt_number)

        new_status = PaymentStatus.SUCCEEDED if succeeded else PaymentStatus.FAILED
        provider_response: dict[str, Any] = {
            "simulated": True,
            "provider": self.provider,
            "outcome": "succeeded" if succeeded else "failed",
            "channel": "direct_charge" if action in _CHARGE_ACTIONS else "customer_channel",
            "attempt_number": attempt_number,
            "failure_reason": reason.value,
            "payment_touched": True,
            **basis,
        }

        # The simulator is the only component that changes payment state
        # (Requirement 14.10).
        self._payments.record_recovery_attempt(
            payment=payment,
            status=new_status,
            action=action,
            failure_reason=None if succeeded else reason,
            provider_response=provider_response,
        )

        return ExecutionResult(
            action=action,
            status=ExecutionStatus.SUCCEEDED if succeeded else ExecutionStatus.FAILED,
            provider_response=provider_response,
            executed_at=self._clock.now(),
        )

    def _decide_outcome(
        self,
        reason: FailureReason,
        action: ActionType,
        payment_id: str,
        attempt_number: int,
    ) -> tuple[bool, dict[str, Any]]:
        """Resolve success, and report how it was decided.

        The reasoning is returned so it can be shown in a demo and stored in the
        audit trail: a judge can see whether an outcome was scripted or drawn.
        """
        scripted = SCRIPTED_OUTCOMES.get((reason, action))
        if scripted is not None:
            return scripted is ScriptedOutcome.ALWAYS_SUCCEED, {
                "decision_basis": "scripted",
                "scripted_outcome": scripted.value,
                "note": (
                    "Deterministic scenario behaviour required by the specification "
                    "(synthetic demonstration value)."
                ),
            }

        threshold = self._settings.scenario_success_probability(reason, action)
        draw = outcome_draw(self._settings.simulation_seed, payment_id, action, attempt_number)

        return draw < threshold, {
            "decision_basis": "seeded_draw",
            "draw": round(draw, 6),
            "success_threshold": threshold,
            "seed": self._settings.simulation_seed,
            "note": (
                "Outcome derived from sha256(seed, payment_id, action, attempt); "
                "reproducible on any machine. Threshold is a synthetic demonstration value."
            ),
        }

    # -- audit -------------------------------------------------------------

    @staticmethod
    def _audit(
        audit: AuditService,
        context: RecoveryContext,
        result: ExecutionResult,
        workflow_id: str | None,
    ) -> None:
        """Record ACTION_EXECUTED or ACTION_FAILED (Requirement 14.12)."""
        failed = result.status is ExecutionStatus.FAILED
        event_type = AuditEventType.ACTION_FAILED if failed else AuditEventType.ACTION_EXECUTED

        audit.record(
            case_id=context.case_id,
            payment_id=context.payment_id,
            stage=WorkflowStage.EXECUTION,
            event_type=event_type,
            message=(
                f"{result.action.value} executed against the payment simulator; "
                f"provider reported {result.status.value}."
            ),
            metadata={
                "action": result.action.value,
                "execution_status": result.status.value,
                "provider_response": result.provider_response,
                "executed_at": result.executed_at.isoformat(),
            },
            workflow_id=workflow_id,
        )


__all__ = [
    "SCRIPTED_OUTCOMES",
    "PaymentSimulatorExecutor",
    "ScriptedOutcome",
    "outcome_draw",
]
