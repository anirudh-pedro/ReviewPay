"""Validated optional AI diagnosis adapter with an offline deterministic provider.

The rich provider response is validated before it is ever converted to the stable
``Diagnosis`` protocol result.  It recommends only; candidate generation, policy,
and execution remain separate authorities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.enums import ActionType, FailureReason
from app.services.context_builder import RecoveryContext
from app.services.diagnosis_engine import Diagnosis, DiagnosisEngine, RuleBasedDiagnosisEngine


class AIDiagnosisPayload(BaseModel):
    """Strict, non-sensitive provider response accepted by the adapter."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    root_cause: FailureReason
    severity: str = Field(pattern="^(LOW|MEDIUM|HIGH)$")
    explanation: str = Field(min_length=8, max_length=800)
    customer_context: str = Field(min_length=3, max_length=500)
    recommended_strategy: ActionType | None = None
    reasoning_factors: tuple[str, ...] = Field(min_length=1, max_length=8)

    @field_validator("reasoning_factors")
    @classmethod
    def _factors_are_safe(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or len(item) > 180 for item in value):
            raise ValueError("Reasoning factors must be bounded non-empty text.")
        return value


@dataclass(frozen=True)
class RichDiagnosis:
    """Validated additional diagnosis evidence for read-only intelligence APIs."""

    root_cause: str
    severity: str
    explanation: str
    customer_context: str
    recommended_strategy: str | None
    reasoning_factors: tuple[str, ...]
    source: str
    fallback_used: bool
    fallback_reason: str | None


@runtime_checkable
class AIDiagnosisProvider(Protocol):
    """Provider boundary; implementations return structured mapping data only."""

    def diagnose(self, context: RecoveryContext) -> Mapping[str, Any]: ...


class LocalMockDiagnosisProvider:
    """Zero-cost local structured provider derived from the trusted rule diagnosis."""

    version = "local-mock-diagnosis-v1"

    def __init__(self, fallback: DiagnosisEngine | None = None) -> None:
        self._fallback = fallback or RuleBasedDiagnosisEngine()

    def diagnose(self, context: RecoveryContext) -> Mapping[str, Any]:
        diagnosis = self._fallback.diagnose(context)
        strategy = (
            ActionType.ESCALATE_HUMAN
            if diagnosis.requires_escalation
            else ActionType.RETRY_LATER
            if diagnosis.is_transient
            else ActionType.CHANGE_PAYMENT_METHOD
            if context.failure_reason is FailureReason.EXPIRED_CARD
            else ActionType.SEND_PAYMENT_LINK
        )
        severity = "HIGH" if diagnosis.requires_escalation else "MEDIUM" if context.attempt_count > 1 else "LOW"
        return {
            "root_cause": diagnosis.failure_reason.value,
            "severity": severity,
            "explanation": diagnosis.explanation,
            "customer_context": (
                f"Historical success rate {context.customer.success_rate:.0%} across "
                f"{context.customer.total_payments} prior payment(s); "
                f"subscription={context.customer.subscription_status.value}."
            ),
            "recommended_strategy": strategy.value,
            "reasoning_factors": (
                "Persisted failure reason",
                "Pre-action customer payment history",
                "Existing retry and recovery history",
            ),
        }


class AIDiagnosisEngine:
    """DiagnosisEngine adapter that guarantees a deterministic safe fallback."""

    version = "ai-diagnosis-adapter-v1"

    def __init__(
        self,
        provider: AIDiagnosisProvider | None = None,
        fallback: DiagnosisEngine | None = None,
    ) -> None:
        self._fallback = fallback or RuleBasedDiagnosisEngine()
        self._provider = provider or LocalMockDiagnosisProvider(self._fallback)
        self.last_analysis: RichDiagnosis | None = None

    def diagnose(self, context: RecoveryContext) -> Diagnosis:
        """Produce the stable core diagnosis after rejecting unsafe provider content."""

        fallback = self._fallback.diagnose(context)
        try:
            payload = AIDiagnosisPayload.model_validate(self._provider.diagnose(context))
            if payload.root_cause is not fallback.failure_reason:
                raise ValueError("Provider root cause disagrees with the persisted failure reason.")
            self.last_analysis = RichDiagnosis(
                root_cause=payload.root_cause.value,
                severity=payload.severity,
                explanation=payload.explanation,
                customer_context=payload.customer_context,
                recommended_strategy=(
                    payload.recommended_strategy.value if payload.recommended_strategy else None
                ),
                reasoning_factors=payload.reasoning_factors,
                source=getattr(self._provider, "version", self.version),
                fallback_used=False,
                fallback_reason=None,
            )
            # The provider may enrich explanation only. It cannot alter category,
            # transience, or escalation semantics that downstream policy depends on.
            return Diagnosis(
                failure_reason=fallback.failure_reason,
                category=fallback.category,
                transience=fallback.transience,
                requires_escalation=fallback.requires_escalation,
                explanation=payload.explanation,
            )
        except Exception as error:  # noqa: BLE001 - provider boundary must never fail the workflow
            self.last_analysis = RichDiagnosis(
                root_cause=fallback.failure_reason.value,
                severity="HIGH" if fallback.requires_escalation else "MEDIUM",
                explanation=fallback.explanation,
                customer_context="Deterministic fallback; provider context was unavailable.",
                recommended_strategy=None,
                reasoning_factors=("Deterministic diagnosis fallback",),
                source="deterministic_diagnosis_fallback",
                fallback_used=True,
                fallback_reason=f"Structured diagnosis rejected ({type(error).__name__}).",
            )
            return fallback


__all__ = [
    "AIDiagnosisEngine",
    "AIDiagnosisPayload",
    "AIDiagnosisProvider",
    "LocalMockDiagnosisProvider",
    "RichDiagnosis",
]
