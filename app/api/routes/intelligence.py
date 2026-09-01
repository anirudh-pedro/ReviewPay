"""Read-only Phase 3 Recovery Intelligence endpoints.

These handlers intentionally compose existing domain services.  They do not train
or persist a model artifact, create recovery actions, mutate payments, or bypass the
workflow policy gate.  Every value is synthetic-demo evidence and is explicitly
marked as such in the response model.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ClockDep, SessionDep, SettingsDep
from app.schemas.common import Money
from app.schemas.intelligence import (
    AdaptiveStrategyRead,
    AgentDiagnosisRead,
    CounterfactualArmRead,
    CounterfactualComparisonRead,
    DiagnosisCustomerContextRead,
    HistoricalLearningEvidenceRead,
    IntelligenceFactorRead,
    ModelTrainingRead,
    RecoveryIntelligenceResponse,
)
from app.schemas.product import ScenarioOverridesRequest
from app.services.recovery_intelligence import (
    AdaptiveStrategy,
    CounterfactualArm,
    HistoricalLearningEvidence,
    RecoveryIntelligence,
    RecoveryIntelligenceService,
)
from app.services.strategy_lab import ScenarioOverrides

router = APIRouter(prefix="/recovery", tags=["recovery-intelligence"])


def _overrides(request: ScenarioOverridesRequest) -> ScenarioOverrides:
    """Map the shared Strategy Lab override schema to the domain value object."""

    return ScenarioOverrides(
        retry_later_delay_minutes=request.retry_later_delay_minutes,
        max_automatic_retries=request.max_automatic_retries,
        repeated_failure_limit=request.repeated_failure_limit,
        high_value_escalation_threshold=request.high_value_escalation_threshold,
        intervention_cost_minor=request.intervention_cost_minor,
        friction_penalty_minor=request.friction_penalty_minor,
    )


def _history_read(value: HistoricalLearningEvidence) -> HistoricalLearningEvidenceRead:
    return HistoricalLearningEvidenceRead(
        cohort=value.cohort,
        synthetic_samples=value.synthetic_samples,
        synthetic_successes=value.synthetic_successes,
        verified_samples=value.verified_samples,
        verified_successes=value.verified_successes,
        total_samples=value.total_samples,
        success_rate=value.success_rate,
        statement=value.statement,
    )


def _strategy_read(option: AdaptiveStrategy, currency: str) -> AdaptiveStrategyRead:
    deterministic = option.deterministic_breakdown
    adaptive = option.adaptive_breakdown
    return AdaptiveStrategyRead(
        action=option.action.value,
        is_candidate=option.is_candidate,
        is_production_selected=option.is_production_selected,
        is_adaptive_recommended=option.is_adaptive_recommended,
        deterministic_probability=option.deterministic_probability,
        learned_probability=option.learned_probability,
        probability_delta=option.probability_delta,
        deterministic_confidence=option.deterministic_confidence,
        model_confidence=option.model_confidence,
        deterministic_expected_recovery_value=Money.of(
            deterministic.expected_recovery_value, currency
        ),
        adaptive_expected_recovery_value=Money.of(
            adaptive.expected_recovery_value, currency
        ),
        intervention_cost=Money.of(adaptive.intervention_cost, currency),
        friction_penalty=Money.of(adaptive.customer_friction_penalty, currency),
        risk_level=option.risk_level.value,
        policy_outcome=option.policy.outcome.value,
        policy_rule_id=option.policy.rule_id,
        policy_reason=option.policy.reason,
        historical_evidence=_history_read(option.historical_evidence),
        learning_factors=[
            IntelligenceFactorRead(
                name=factor.name,
                value=str(factor.value),
                influence=factor.influence,
                description=factor.description,
            )
            for factor in option.learning_factors
        ],
        rejected_reason=option.rejected_reason,
        simulated_would_recover=option.simulated_would_recover,
        simulation_basis=option.simulation_basis,
    )


def _counterfactual_arm_read(
    arm: CounterfactualArm, currency: str
) -> CounterfactualArmRead:
    return CounterfactualArmRead(
        label=arm.label,
        action=arm.action.value if arm.action is not None else None,
        policy_outcome=arm.policy.outcome.value if arm.policy is not None else None,
        policy_rule_id=arm.policy.rule_id if arm.policy is not None else None,
        policy_reason=arm.policy.reason if arm.policy is not None else None,
        probability=arm.probability,
        expected_recovery_value=Money.of(arm.expected_recovery_value, currency),
        projected_recovered=Money.of(arm.projected_recovered, currency),
        simulated_would_recover=arm.simulated_would_recover,
        simulation_basis=arm.simulation_basis,
    )


def _response_read(result: RecoveryIntelligence) -> RecoveryIntelligenceResponse:
    diagnosis = result.diagnosis
    context = diagnosis.customer_context
    counterfactual = result.counterfactual
    return RecoveryIntelligenceResponse(
        case_id=result.case_id,
        payment_id=result.payment_id,
        amount=Money.of(result.amount, result.currency),
        failure_detected=result.failure_detected,
        diagnosis=AgentDiagnosisRead(
            root_cause=diagnosis.root_cause,
            severity=diagnosis.severity,
            customer_context=DiagnosisCustomerContextRead(
                history_available=context.history_available,
                total_payments=context.total_payments,
                success_rate=context.success_rate,
                subscription_status=context.subscription_status,
                is_returning_customer=context.is_returning_customer,
                successful_recovery_actions=list(context.successful_recovery_actions),
                summary=context.summary,
            ),
            recommended_recovery_approach=diagnosis.recommended_recovery_approach,
            reasoning=diagnosis.reasoning,
            source=diagnosis.source,
            fallback_used=diagnosis.fallback_used,
            fallback_reason=diagnosis.fallback_reason,
        ),
        model=ModelTrainingRead(
            model_version=result.model.model_version,
            training_samples=result.model.training_samples,
            synthetic_samples=result.model.synthetic_samples,
            verified_outcome_samples=result.model.verified_outcome_samples,
            bounded_window=result.model.bounded_window,
            fallback_used=result.model.fallback_used,
            fallback_reason=result.model.fallback_reason,
        ),
        production_selected_action=(
            result.production_selected_action.value
            if result.production_selected_action is not None
            else None
        ),
        adaptive_recommended_action=(
            result.adaptive_recommended_action.value
            if result.adaptive_recommended_action is not None
            else None
        ),
        adaptive_reasoning=result.adaptive_reasoning,
        candidates=[_strategy_read(option, result.currency) for option in result.candidates],
        counterfactual=CounterfactualComparisonRead(
            basis=counterfactual.basis,
            baseline=_counterfactual_arm_read(counterfactual.baseline, result.currency),
            revivepay=_counterfactual_arm_read(counterfactual.revivepay, result.currency),
            projected_recovered_uplift=Money.of(
                counterfactual.projected_recovered_uplift, result.currency
            ),
            projected_recovered_uplift_pct=counterfactual.projected_recovered_uplift_pct,
            expected_recovery_value_uplift=Money.of(
                counterfactual.expected_recovery_value_uplift, result.currency
            ),
            notice=counterfactual.notice,
        ),
    )


@router.get(
    "/cases/{case_id}/intelligence",
    response_model=RecoveryIntelligenceResponse,
    summary="Explain bounded diagnosis, learned probability, and counterfactual evidence",
)
def get_recovery_intelligence(
    case_id: str,
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> RecoveryIntelligenceResponse:
    """Return read-only Phase 3 evidence using the live backend configuration."""

    result = RecoveryIntelligenceService(
        session=session, clock=clock, settings=settings
    ).evaluate(case_id)
    return _response_read(result)


@router.post(
    "/cases/{case_id}/intelligence/simulate",
    response_model=RecoveryIntelligenceResponse,
    summary="Run a read-only bounded intelligence what-if evaluation",
)
def simulate_recovery_intelligence(
    case_id: str,
    request: ScenarioOverridesRequest,
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> RecoveryIntelligenceResponse:
    """Apply Strategy Lab overrides only to this advisory intelligence projection."""

    result = RecoveryIntelligenceService(
        session=session, clock=clock, settings=settings
    ).evaluate(case_id, _overrides(request))
    return _response_read(result)


# ---------------------------------------------------------------------------
# Focused Phase 3 read models
# ---------------------------------------------------------------------------
# The aggregate intelligence payload remains the canonical response.  These
# typed, read-only routes expose focused entry points for dashboard integrations
# without adding any execution capability or a second decision path.

from app.schemas.intelligence import ModelStatusResponse


def _case_intelligence_read(case_id: str, session, clock, settings) -> RecoveryIntelligenceResponse:
    result = RecoveryIntelligenceService(
        session=session, clock=clock, settings=settings
    ).evaluate(case_id)
    return _response_read(result)


@router.get(
    "/intelligence/model-status",
    response_model=ModelStatusResponse,
    summary="Configured predictor status and bounded training provenance",
)
def get_model_status(
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> ModelStatusResponse:
    """Return safe model provenance; no artifact contents or credentials are exposed."""

    from app.core.container import get_recovery_predictor
    from app.ml.features import FEATURE_SCHEMA_VERSION
    from app.services.recovery_intelligence import BoundedRecoveryProbabilityModel

    predictor = get_recovery_predictor(settings)
    training = BoundedRecoveryProbabilityModel(session, clock, settings).summary
    fallback_mode = bool(getattr(predictor, "is_fallback", False))
    active_predictor = getattr(predictor, "model_version", predictor.__class__.__name__)
    if settings.recovery_predictor_impl == "deterministic":
        mode = "deterministic_default"
    elif fallback_mode:
        mode = "deterministic_fallback"
    else:
        mode = "local_model"
    return ModelStatusResponse(
        active_predictor=str(active_predictor),
        mode=mode,
        fallback_mode=fallback_mode,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        training=ModelTrainingRead(
            model_version=training.model_version,
            training_samples=training.training_samples,
            synthetic_samples=training.synthetic_samples,
            verified_outcome_samples=training.verified_outcome_samples,
            bounded_window=training.bounded_window,
            fallback_used=training.fallback_used,
            fallback_reason=training.fallback_reason,
        ),
    )


@router.get("/cases/{case_id}/prediction", response_model=RecoveryIntelligenceResponse)
def get_case_prediction(case_id: str, session: SessionDep, clock: ClockDep, settings: SettingsDep):
    """Return per-candidate prediction evidence for a case (read-only)."""

    return _case_intelligence_read(case_id, session, clock, settings)


@router.get("/cases/{case_id}/strategy-evaluation", response_model=RecoveryIntelligenceResponse)
def get_strategy_evaluation(case_id: str, session: SessionDep, clock: ClockDep, settings: SettingsDep):
    """Return policy-aware ERV ranking evidence for a case (read-only)."""

    return _case_intelligence_read(case_id, session, clock, settings)


@router.get("/cases/{case_id}/ai-diagnosis", response_model=RecoveryIntelligenceResponse)
def get_ai_diagnosis(case_id: str, session: SessionDep, clock: ClockDep, settings: SettingsDep):
    """Return structured diagnosis evidence and deterministic fallback provenance."""

    return _case_intelligence_read(case_id, session, clock, settings)


@router.get("/cases/{case_id}/historical-insights", response_model=RecoveryIntelligenceResponse)
def get_historical_insights(case_id: str, session: SessionDep, clock: ClockDep, settings: SettingsDep):
    """Return bounded historical evidence excluding the evaluated case label."""

    return _case_intelligence_read(case_id, session, clock, settings)


@router.get("/cases/{case_id}/decision-explanation", response_model=RecoveryIntelligenceResponse)
def get_decision_explanation(case_id: str, session: SessionDep, clock: ClockDep, settings: SettingsDep):
    """Return full model, business-value, policy, and rejection reasoning."""

    return _case_intelligence_read(case_id, session, clock, settings)
