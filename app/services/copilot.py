"""AI Recovery Copilot with provider abstraction and deterministic fallback.

This module acts as an advisory copilot layer for recovery intelligence.
It provides structured diagnosis narrative, confidence scoring, action recommendation,
and ERV-based rationale while strictly delegating execution authority to the PolicyEngine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings, get_settings
from app.core.enums import ActionType, FailureReason
from app.ml.deterministic_scorer import DeterministicRecoveryScorer
from app.services.context_builder import RecoveryContext
from app.services.diagnosis_engine import DiagnosisEngine, RuleBasedDiagnosisEngine
from app.services.expected_value import ExpectedRecoveryCalculator


class CopilotPayload(BaseModel):
    """Strict schema accepted from AI Copilot providers."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    root_cause: FailureReason
    severity: str = Field(pattern="^(LOW|MEDIUM|HIGH)$")
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(min_length=8, max_length=1000)
    recommended_action: ActionType
    strategic_reasoning: str = Field(min_length=8, max_length=1000)
    key_risk_factors: tuple[str, ...] = Field(min_length=1, max_length=8)


@dataclass(frozen=True)
class CopilotAnalysis:
    """Validated copilot result exposed to routes and UI."""

    root_cause: str
    severity: str
    confidence: float
    explanation: str
    recommended_action: ActionType
    strategic_reasoning: str
    key_risk_factors: tuple[str, ...]
    provider_name: str
    fallback_used: bool
    fallback_reason: str | None


@runtime_checkable
class AICopilotProvider(Protocol):
    """Provider boundary for external or mock AI LLM providers."""

    provider_name: str

    def analyze(self, context: RecoveryContext) -> Mapping[str, Any]: ...


class LocalMockCopilotProvider:
    """Zero-external-dependency local provider derived from rule diagnoser & scorer."""

    provider_name = "local_mock_copilot"

    def __init__(
        self,
        diagnoser: DiagnosisEngine | None = None,
        scorer: DeterministicRecoveryScorer | None = None,
    ) -> None:
        self._diagnoser = diagnoser or RuleBasedDiagnosisEngine()
        self._scorer = scorer or DeterministicRecoveryScorer()

    def analyze(self, context: RecoveryContext) -> Mapping[str, Any]:
        diagnosis = self._diagnoser.diagnose(context)
        
        # Determine recommended strategy based on failure cause & history
        if diagnosis.requires_escalation:
            rec_action = ActionType.ESCALATE_HUMAN
        elif diagnosis.is_transient:
            rec_action = ActionType.RETRY_LATER
        elif context.failure_reason is FailureReason.EXPIRED_CARD:
            rec_action = ActionType.CHANGE_PAYMENT_METHOD
        elif context.failure_reason is FailureReason.CHECKOUT_ABANDONMENT:
            rec_action = ActionType.SEND_REMINDER
        else:
            rec_action = ActionType.SEND_PAYMENT_LINK

        prediction = self._scorer.predict(context, rec_action)
        severity = "HIGH" if diagnosis.requires_escalation or context.amount >= 5_000_000 else "MEDIUM" if context.attempt_count > 1 else "LOW"

        return {
            "root_cause": diagnosis.failure_reason.value,
            "severity": severity,
            "confidence": prediction.confidence,
            "explanation": diagnosis.explanation,
            "recommended_action": rec_action.value,
            "strategic_reasoning": (
                f"Selected {rec_action.value} with estimated probability {prediction.probability:.0%}. "
                f"Customer history: success rate {context.customer.success_rate:.0%} across "
                f"{context.customer.total_payments} prior payment(s)."
            ),
            "key_risk_factors": (
                f"Failure reason: {context.failure_reason.value}",
                f"Attempt count: {context.attempt_count}",
                f"Customer subscription: {context.customer.subscription_status.value}",
            ),
        }


class AICopilotService:
    """Main Copilot service with guaranteed deterministic fallback."""

    def __init__(
        self,
        provider: AICopilotProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._diagnoser = RuleBasedDiagnosisEngine()
        self._scorer = DeterministicRecoveryScorer()
        self._calculator = ExpectedRecoveryCalculator(self._settings)
        self._provider = provider or LocalMockCopilotProvider(self._diagnoser, self._scorer)

    def analyze(self, context: RecoveryContext) -> CopilotAnalysis:
        """Analyze a recovery context using copilot with explicit fallback safety."""
        try:
            raw_data = self._provider.analyze(context)
            payload = CopilotPayload.model_validate(raw_data)
            return CopilotAnalysis(
                root_cause=payload.root_cause.value,
                severity=payload.severity,
                confidence=payload.confidence,
                explanation=payload.explanation,
                recommended_action=payload.recommended_action,
                strategic_reasoning=payload.strategic_reasoning,
                key_risk_factors=payload.key_risk_factors,
                provider_name=getattr(self._provider, "provider_name", "custom_provider"),
                fallback_used=False,
                fallback_reason=None,
            )
        except Exception as error:  # noqa: BLE001 - fallback boundary must be bulletproof
            diagnosis = self._diagnoser.diagnose(context)
            rec_action = ActionType.RETRY_LATER if diagnosis.is_transient else ActionType.SEND_PAYMENT_LINK
            prediction = self._scorer.predict(context, rec_action)
            
            return CopilotAnalysis(
                root_cause=diagnosis.failure_reason.value,
                severity="HIGH" if diagnosis.requires_escalation else "MEDIUM",
                confidence=prediction.confidence,
                explanation=diagnosis.explanation,
                recommended_action=rec_action,
                strategic_reasoning=f"Deterministic fallback reasoning for cause {diagnosis.failure_reason.value}.",
                key_risk_factors=("Deterministic fallback used", f"Error: {type(error).__name__}"),
                provider_name="deterministic_fallback",
                fallback_used=True,
                fallback_reason=f"Copilot provider failed ({type(error).__name__}): {error}",
            )


__all__ = [
    "AICopilotProvider",
    "AICopilotService",
    "CopilotAnalysis",
    "CopilotPayload",
    "LocalMockCopilotProvider",
]
