"""Policy engine: the mandatory gate before execution.

No recovery action reaches the action executor without a verdict from here
(Requirement 13.9). The decision engine proposes; this engine permits. That
separation is the system's core safety property: a scoring change can never, by
itself, cause money to move.

The engine itself holds no rules. It runs the ordered rule set from
``policy_rules`` and returns the first verdict, so adding or reordering a rule is a
change to one list (Requirement 13.11, 13.12).

Three outcomes, and only three:

- ``APPROVED``  — the workflow may execute the action
- ``BLOCKED``   — the case stops
- ``ESCALATED`` — a human takes over; nothing is executed

Every verdict is persisted on the recovery action and audited (Requirement 13.10).
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.enums import ActionType, AuditEventType, PolicyOutcome, WorkflowStage
from app.core.logging import get_logger
from app.models import RecoveryAction
from app.services.audit_service import AuditService
from app.services.context_builder import RecoveryContext
from app.services.decision_engine import RecoveryDecision
from app.services.policy_rules import (
    DEFAULT_RULES,
    PolicyInput,
    PolicyResult,
    PolicyRule,
    default_approval,
)

logger = get_logger("policy")

#: Audit event per outcome (Requirement 13.10).
_EVENT_BY_OUTCOME = {
    PolicyOutcome.APPROVED: AuditEventType.POLICY_APPROVED,
    PolicyOutcome.BLOCKED: AuditEventType.POLICY_BLOCKED,
    PolicyOutcome.ESCALATED: AuditEventType.POLICY_ESCALATED,
}


class PolicyEngine:
    """Evaluates a proposed recovery action against the configured safety rules."""

    def __init__(
        self,
        settings: Settings | None = None,
        rules: tuple[PolicyRule, ...] | None = None,
        supported_actions: frozenset[ActionType] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._rules = rules if rules is not None else DEFAULT_RULES
        # Defaults to every action; the workflow narrows this to what the
        # configured executor actually supports.
        self._supported_actions = (
            supported_actions if supported_actions is not None else frozenset(ActionType)
        )

    @property
    def rule_ids(self) -> tuple[str, ...]:
        """Rule identifiers in evaluation order."""
        return tuple(rule.rule_id for rule in self._rules)

    def evaluate(
        self,
        context: RecoveryContext,
        decision: RecoveryDecision,
    ) -> PolicyResult:
        """Return a verdict for the selected action (Requirement 13.1).

        Total by construction: if no rule objects, the default approval applies, so
        the caller never has to handle a missing verdict.
        """
        data = PolicyInput(
            context=context,
            decision=decision,
            settings=self._settings,
            supported_actions=self._supported_actions,
        )

        for rule in self._rules:
            verdict = rule.evaluate(data)
            if verdict is not None:
                logger.info(
                    "policy | %s | %s -> %s (%s)",
                    context.payment_id,
                    decision.selected_action.value,
                    verdict.outcome.value,
                    verdict.rule_id,
                )
                return verdict

        verdict = default_approval(data)
        logger.info(
            "policy | %s | %s -> %s (%s)",
            context.payment_id,
            decision.selected_action.value,
            verdict.outcome.value,
            verdict.rule_id,
        )
        return verdict

    # -- persistence and audit --------------------------------------------

    @staticmethod
    def apply_to_action(action: RecoveryAction, result: PolicyResult) -> RecoveryAction:
        """Record the verdict on the recovery action (Requirement 13.10)."""
        from app.core.enums import ActionStatus

        action.policy_outcome = result.outcome
        action.policy_rule_id = result.rule_id
        action.policy_reason = result.reason
        action.status = {
            PolicyOutcome.APPROVED: ActionStatus.APPROVED,
            PolicyOutcome.BLOCKED: ActionStatus.BLOCKED,
            PolicyOutcome.ESCALATED: ActionStatus.ESCALATED,
        }[result.outcome]
        return action

    def audit(
        self,
        audit: AuditService,
        context: RecoveryContext,
        decision: RecoveryDecision,
        result: PolicyResult,
        workflow_id: str | None = None,
    ) -> None:
        """Record the verdict, the deciding rule, and the reason.

        The configured limits are recorded alongside the verdict so that a reviewer
        reading the trail months later can see the thresholds that were in force at
        the time, not just today's configuration.
        """
        audit.record(
            case_id=context.case_id,
            payment_id=context.payment_id,
            stage=WorkflowStage.POLICY,
            event_type=_EVENT_BY_OUTCOME[result.outcome],
            message=result.reason,
            metadata={
                "evaluated_action": decision.selected_action.value,
                "policy_outcome": result.outcome.value,
                "policy_rule_id": result.rule_id,
                "policy_reason": result.reason,
                "expected_recovery_value": decision.expected_recovery_value,
                "probability": decision.probability,
                "confidence": decision.confidence,
                "risk_level": decision.risk_level.value,
                "attempt_count": context.attempt_count,
                "amount": context.amount,
                "currency": context.currency,
                "rules_evaluated": list(self.rule_ids),
                "limits": {
                    "max_automatic_retries": self._settings.max_automatic_retries,
                    "repeated_failure_limit": self._settings.repeated_failure_limit,
                    "high_value_escalation_threshold": (
                        self._settings.high_value_escalation_threshold
                    ),
                    "allow_human_escalation": self._settings.allow_human_escalation,
                },
            },
            workflow_id=workflow_id,
        )


__all__ = ["PolicyEngine"]
