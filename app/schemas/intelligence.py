"""Read models for the Phase 3 Recovery Intelligence Layer.

These schemas are intentionally additive. They expose read-only, explicitly
synthetic intelligence evidence without changing the stable workflow, recovery, or
Strategy Lab contracts.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import Money, SyntheticNotice


class DiagnosisCustomerContextRead(BaseModel):
    """Non-identifying customer context used by the diagnosis agent."""

    history_available: bool
    total_payments: int
    success_rate: float
    subscription_status: str
    is_returning_customer: bool
    successful_recovery_actions: list[str] = Field(default_factory=list)
    summary: str


class AgentDiagnosisRead(BaseModel):
    """Structured diagnosis-agent evidence with deterministic fallback provenance."""

    root_cause: str
    severity: str
    customer_context: DiagnosisCustomerContextRead
    recommended_recovery_approach: str | None = None
    reasoning: str
    source: str
    fallback_used: bool
    fallback_reason: str | None = None


class IntelligenceFactorRead(BaseModel):
    """One explainable learned-prediction contribution."""

    name: str
    value: str
    influence: float
    description: str


class HistoricalLearningEvidenceRead(BaseModel):
    """Comparable synthetic and verified observations for one candidate."""

    cohort: str
    synthetic_samples: int
    synthetic_successes: int
    verified_samples: int
    verified_successes: int
    total_samples: int
    success_rate: float | None = None
    statement: str


class ModelTrainingRead(BaseModel):
    """Bounded model provenance, not a claim of unrestricted online learning."""

    model_version: str
    training_samples: int
    synthetic_samples: int
    verified_outcome_samples: int
    bounded_window: str
    fallback_used: bool
    fallback_reason: str | None = None


class AdaptiveStrategyRead(BaseModel):
    """Deterministic-versus-learned evaluation of one production candidate."""

    action: str
    is_candidate: bool
    is_production_selected: bool
    is_adaptive_recommended: bool
    deterministic_probability: float
    learned_probability: float
    probability_delta: float
    deterministic_confidence: float
    model_confidence: float
    deterministic_expected_recovery_value: Money
    adaptive_expected_recovery_value: Money
    intervention_cost: Money
    friction_penalty: Money
    risk_level: str
    policy_outcome: str
    policy_rule_id: str
    policy_reason: str
    historical_evidence: HistoricalLearningEvidenceRead
    learning_factors: list[IntelligenceFactorRead] = Field(default_factory=list)
    rejected_reason: str
    simulated_would_recover: bool
    simulation_basis: str


class CounterfactualArmRead(BaseModel):
    """One fair, read-only arm of a synthetic strategy counterfactual."""

    label: str
    action: str | None = None
    policy_outcome: str | None = None
    policy_rule_id: str | None = None
    policy_reason: str | None = None
    probability: float
    expected_recovery_value: Money
    projected_recovered: Money
    simulated_would_recover: bool
    simulation_basis: str


class CounterfactualComparisonRead(BaseModel):
    """Baseline RETRY_NOW against the advisory RevivePay recommendation."""

    basis: str
    baseline: CounterfactualArmRead
    revivepay: CounterfactualArmRead
    projected_recovered_uplift: Money
    projected_recovered_uplift_pct: float | None = None
    expected_recovery_value_uplift: Money
    notice: str


class RecoveryIntelligenceResponse(SyntheticNotice):
    """Complete Phase 3 evidence for one recovery case."""

    case_id: str
    payment_id: str
    amount: Money
    failure_detected: str
    diagnosis: AgentDiagnosisRead
    model: ModelTrainingRead
    production_selected_action: str | None = None
    adaptive_recommended_action: str | None = None
    adaptive_reasoning: str
    candidates: list[AdaptiveStrategyRead]
    counterfactual: CounterfactualComparisonRead


__all__ = [
    "AdaptiveStrategyRead",
    "AgentDiagnosisRead",
    "CounterfactualArmRead",
    "CounterfactualComparisonRead",
    "DiagnosisCustomerContextRead",
    "HistoricalLearningEvidenceRead",
    "IntelligenceFactorRead",
    "ModelTrainingRead",
    "RecoveryIntelligenceResponse",
]


class ModelStatusResponse(SyntheticNotice):
    """Status of the configured local prediction path without exposing credentials."""

    active_predictor: str
    mode: str
    fallback_mode: bool
    feature_schema_version: str
    training: ModelTrainingRead


__all__.append("ModelStatusResponse")
