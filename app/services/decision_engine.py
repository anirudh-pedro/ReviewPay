"""Recovery decision engine.

Scores every candidate, ranks by expected recovery value, and selects the best one.
This is where the system's central claim is enforced: **optimise expected recovered
revenue, not retry count**. A more expensive action wins whenever its gross
advantage exceeds its extra cost.

The engine returns a data structure and nothing more. It performs no execution and
changes no payment state (Requirement 11.4, 27.5). Execution authority belongs to
the action executor, and it is only reachable after the policy engine approves.

The engine contains no per-failure-reason branching: it consumes whatever candidate
list the generator produced (Requirement 9.9).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import ActionType, AuditEventType, RiskLevel, WorkflowStage
from app.core.logging import get_logger
from app.ml.predictor import PredictionResult, RecoveryPredictor
from app.services.audit_service import AuditService
from app.services.context_builder import RecoveryContext
from app.services.diagnosis_engine import Diagnosis
from app.services.expected_value import ExpectedRecoveryCalculator, ExpectedValueBreakdown

logger = get_logger("decision")


@dataclass(frozen=True)
class ScoredCandidate:
    """One candidate action with its prediction, valuation, and risk."""

    action: ActionType
    prediction: PredictionResult
    breakdown: ExpectedValueBreakdown
    risk_level: RiskLevel

    @property
    def probability(self) -> float:
        return self.prediction.probability

    @property
    def confidence(self) -> float:
        return self.prediction.confidence

    @property
    def expected_recovery_value(self) -> int:
        return self.breakdown.expected_recovery_value

    def to_alternative(self) -> dict[str, Any]:
        """The shape used in the explanation's alternatives array."""
        return {
            "action": self.action.value,
            "probability": self.probability,
            "expected_recovery_value": self.expected_recovery_value,
        }


@dataclass(frozen=True)
class DecisionExplanation:
    """Why this action was chosen, in a form a UI can render directly."""

    selected_action: ActionType
    reason: str
    probability: float
    expected_recovery_value: int
    confidence: float
    alternatives: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_action": self.selected_action.value,
            "reason": self.reason,
            "probability": self.probability,
            "expected_recovery_value": self.expected_recovery_value,
            "confidence": self.confidence,
            "alternatives": [dict(item) for item in self.alternatives],
        }


@dataclass(frozen=True)
class RecoveryDecision:
    """The selected action, its valuation, and the full ranking behind it."""

    selected_action: ActionType
    probability: float
    confidence: float
    expected_recovery_value: int
    breakdown: ExpectedValueBreakdown
    risk_level: RiskLevel
    model_version: str
    ranked: tuple[ScoredCandidate, ...]
    explanation: DecisionExplanation

    @property
    def selected(self) -> ScoredCandidate | None:
        """The scored candidate that was selected, when one was scored."""
        for candidate in self.ranked:
            if candidate.action is self.selected_action:
                return candidate
        return None

    def ranking_metadata(self) -> list[dict[str, Any]]:
        """Ordered candidate summary for audit metadata."""
        return [
            {
                "action": candidate.action.value,
                "probability": candidate.probability,
                "confidence": candidate.confidence,
                "expected_recovery_value": candidate.expected_recovery_value,
                "gross_expected_recovery": candidate.breakdown.gross_expected_recovery,
                "intervention_cost": candidate.breakdown.intervention_cost,
                "customer_friction_penalty": candidate.breakdown.customer_friction_penalty,
                "risk_level": candidate.risk_level.value,
            }
            for candidate in self.ranked
        ]


class RecoveryDecisionEngine:
    """Ranks candidate recovery actions and selects the most valuable one."""

    def __init__(
        self,
        predictor: RecoveryPredictor,
        calculator: ExpectedRecoveryCalculator,
        settings: Settings | None = None,
    ) -> None:
        self._predictor = predictor
        self._calculator = calculator
        self._settings = settings or get_settings()

    # -- public API --------------------------------------------------------

    def decide(
        self,
        context: RecoveryContext,
        diagnosis: Diagnosis,
        candidates: list[ActionType],
        *,
        audit: AuditService | None = None,
        workflow_id: str | None = None,
    ) -> RecoveryDecision:
        """Score, rank, and select (Requirement 11.1-11.3).

        ``audit`` is optional so the decision path can be exercised as a pure
        function in tests; the workflow always supplies it.
        """
        if not candidates:
            decision = self._fallback_decision(context, diagnosis)
        else:
            scored = [self._score(context, action) for action in candidates]
            ranked = self._rank(scored)
            decision = self._build_decision(ranked[0], ranked, context)

        if audit is not None:
            self._audit(audit, context, decision, workflow_id)

        logger.info(
            "decision | %s | selected=%s p=%.3f erv=%s risk=%s",
            context.payment_id,
            decision.selected_action.value,
            decision.probability,
            decision.expected_recovery_value,
            decision.risk_level.value,
        )
        return decision

    # -- scoring and ranking ----------------------------------------------

    def _score(self, context: RecoveryContext, action: ActionType) -> ScoredCandidate:
        prediction = self._predictor.predict(context, action)
        breakdown = self._calculator.calculate(
            amount=context.amount,
            probability=prediction.probability,
            action=action,
        )
        return ScoredCandidate(
            action=action,
            prediction=prediction,
            breakdown=breakdown,
            risk_level=self._risk_level(context, action),
        )

    def _rank(self, scored: list[ScoredCandidate]) -> tuple[ScoredCandidate, ...]:
        """Order by descending expected recovery value (Requirement 11.2).

        Ties break deterministically: higher probability first, then the cheaper
        intervention, then the declaration order of ``ActionType``. Every component
        of the key is a total order, so ranking never depends on input order or on
        dictionary iteration.
        """
        declaration_order = {action: index for index, action in enumerate(ActionType)}

        return tuple(
            sorted(
                scored,
                key=lambda candidate: (
                    -candidate.expected_recovery_value,
                    -candidate.probability,
                    candidate.breakdown.intervention_cost,
                    declaration_order[candidate.action],
                ),
            )
        )

    def _risk_level(self, context: RecoveryContext, action: ActionType) -> RiskLevel:
        """Classify how risky performing this action would be."""
        if action in ActionType.terminal_actions():
            # Escalating or stopping moves no money.
            return RiskLevel.LOW
        if context.amount > self._settings.high_value_escalation_threshold:
            return RiskLevel.HIGH
        if action in ActionType.retry_actions():
            return RiskLevel.LOW
        return RiskLevel.MEDIUM

    # -- assembly ----------------------------------------------------------

    def _build_decision(
        self,
        winner: ScoredCandidate,
        ranked: tuple[ScoredCandidate, ...],
        context: RecoveryContext,
    ) -> RecoveryDecision:
        alternatives = tuple(
            candidate.to_alternative() for candidate in ranked if candidate.action is not winner.action
        )

        explanation = DecisionExplanation(
            selected_action=winner.action,
            reason=self._reason(winner, ranked, context),
            probability=winner.probability,
            expected_recovery_value=winner.expected_recovery_value,
            confidence=winner.confidence,
            alternatives=alternatives,
        )

        return RecoveryDecision(
            selected_action=winner.action,
            probability=winner.probability,
            confidence=winner.confidence,
            expected_recovery_value=winner.expected_recovery_value,
            breakdown=winner.breakdown,
            risk_level=winner.risk_level,
            model_version=winner.prediction.model_version,
            ranked=ranked,
            explanation=explanation,
        )

    @staticmethod
    def _reason(
        winner: ScoredCandidate,
        ranked: tuple[ScoredCandidate, ...],
        context: RecoveryContext,
    ) -> str:
        """Name the action and the expected-value basis (Requirement 12.3)."""
        sentence = (
            f"{winner.action.value} was selected because it has the highest expected "
            f"recovery value ({winner.expected_recovery_value} {context.currency} minor units) "
            f"among the {len(ranked)} evaluated candidate action(s)."
        )

        runner_up = next(
            (candidate for candidate in ranked if candidate.action is not winner.action), None
        )
        if runner_up is not None:
            margin = winner.expected_recovery_value - runner_up.expected_recovery_value
            sentence += (
                f" It beats {runner_up.action.value} by {margin} minor units, driven by a "
                f"recovery probability of {winner.probability:.3f} against "
                f"{runner_up.probability:.3f}."
            )
        return sentence

    def _fallback_decision(
        self, context: RecoveryContext, diagnosis: Diagnosis
    ) -> RecoveryDecision:
        """Disposition when no candidate is available (Requirement 11.5).

        Hands off to a human when the diagnosis permits it, otherwise stops. Either
        way the case gets a recorded, auditable outcome rather than silently
        stalling.
        """
        human_allowed = diagnosis.permits_human_handling and self._settings.allow_human_escalation
        action = ActionType.ESCALATE_HUMAN if human_allowed else ActionType.STOP

        breakdown = self._calculator.calculate(
            amount=context.amount, probability=0.0, action=action
        )
        reason = (
            f"No candidate recovery action was available for "
            f"{diagnosis.failure_reason.value}; {action.value} was selected because "
            + (
                "the diagnosis permits human handling."
                if human_allowed
                else "automated recovery is not safe and human handling is unavailable."
            )
        )

        explanation = DecisionExplanation(
            selected_action=action,
            reason=reason,
            probability=0.0,
            expected_recovery_value=breakdown.expected_recovery_value,
            confidence=0.0,
            alternatives=(),
        )

        return RecoveryDecision(
            selected_action=action,
            probability=0.0,
            confidence=0.0,
            expected_recovery_value=breakdown.expected_recovery_value,
            breakdown=breakdown,
            risk_level=RiskLevel.LOW,
            model_version="none",
            ranked=(),
            explanation=explanation,
        )

    # -- audit -------------------------------------------------------------

    @staticmethod
    def _audit(
        audit: AuditService,
        context: RecoveryContext,
        decision: RecoveryDecision,
        workflow_id: str | None,
    ) -> None:
        """Record the evaluation and the selection (Requirement 11.6)."""
        audit.record(
            case_id=context.case_id,
            payment_id=context.payment_id,
            stage=WorkflowStage.EVALUATION,
            event_type=AuditEventType.RECOVERY_OPTIONS_EVALUATED,
            message=(
                f"Evaluated {len(decision.ranked)} candidate action(s), ranked by expected "
                "recovery value."
            ),
            metadata={
                "candidates": decision.ranking_metadata(),
                "candidate_count": len(decision.ranked),
                "model_version": decision.model_version,
            },
            workflow_id=workflow_id,
        )

        audit.record(
            case_id=context.case_id,
            payment_id=context.payment_id,
            stage=WorkflowStage.DECISION,
            event_type=AuditEventType.RECOVERY_DECISION_SELECTED,
            message=decision.explanation.reason,
            metadata={
                "selected_action": decision.selected_action.value,
                "probability": decision.probability,
                "confidence": decision.confidence,
                "expected_recovery_value": decision.expected_recovery_value,
                "erv_breakdown": decision.breakdown.to_dict(),
                "risk_level": decision.risk_level.value,
                "model_version": decision.model_version,
                "alternatives": [dict(item) for item in decision.explanation.alternatives],
                "explanation": decision.explanation.reason,
            },
            workflow_id=workflow_id,
        )


__all__ = [
    "DecisionExplanation",
    "RecoveryDecision",
    "RecoveryDecisionEngine",
    "ScoredCandidate",
]
