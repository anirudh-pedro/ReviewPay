"""Bounded, explainable recovery intelligence.

This module is deliberately a read-only advisory layer.  It does not replace the
live deterministic workflow, policy gate, payment simulator, or verifier.  Its
purpose is to make the existing system easier to inspect while proving how a
lightweight learned probability can be introduced safely:

* a structured local diagnosis agent enriches the deterministic diagnosis and
  falls back to it whenever its own analysis cannot be produced;
* a pure-Python empirical-Bayes calibrator trains on a bounded synthetic simulator
  corpus plus a capped window of independently verified outcomes;
* every adaptive score still goes through the one ExpectedRecoveryCalculator and
  the real PolicyEngine; and
* counterfactuals call the simulator's read-only prediction path and are labelled
  as synthetic projections rather than financial facts.

No request writes model weights, creates recovery actions, mutates payments, or
records audit events.  Rebuilding the small model per read keeps learning bounded,
reproducible, and transparent for the synthetic demo.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import log1p
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings, get_settings
from app.core.enums import (
    ActionType,
    FailureReason,
    PaymentStatus,
    PolicyOutcome,
    RiskLevel,
    SubscriptionStatus,
)
from app.core.errors import RecordNotFound
from app.integrations.payment_simulator import PaymentSimulatorExecutor
from app.ml.deterministic_scorer import DeterministicRecoveryScorer
from app.ml.predictor import PredictionResult, ScoringFactor
from app.models import Customer, Payment, RecoveryAction, RecoveryCase, RecoveryOutcome
from app.services.candidate_generator import RecoveryActionCandidateGenerator
from app.services.context_builder import RecoveryContext, RecoveryContextBuilder
from app.services.decision_engine import RecoveryDecisionEngine
from app.services.diagnosis_engine import Diagnosis, DiagnosisEngine, RuleBasedDiagnosisEngine
from app.services.expected_value import ExpectedRecoveryCalculator, ExpectedValueBreakdown
from app.services.policy_engine import PolicyEngine
from app.services.policy_rules import PolicyResult
from app.services.strategy_lab import ScenarioOverrides

MODEL_VERSION = "bounded-empirical-bayes-v1"
MAX_SYNTHETIC_CASES = 60
MAX_VERIFIED_OUTCOMES = 120
PRIOR_STRENGTH = 12.0


@dataclass(frozen=True)
class CustomerIntelligenceContext:
    """A whitelisted, non-identifying customer context for the UI."""

    history_available: bool
    total_payments: int
    success_rate: float
    subscription_status: str
    is_returning_customer: bool
    successful_recovery_actions: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class AgentDiagnosis:
    """Structured diagnosis-agent output separate from the stable Diagnosis model."""

    root_cause: str
    severity: str
    customer_context: CustomerIntelligenceContext
    recommended_recovery_approach: str | None
    reasoning: str
    source: str
    fallback_used: bool
    fallback_reason: str | None


@dataclass(frozen=True)
class TrainingSample:
    """One bounded, non-identifying learning example."""

    action: ActionType
    failure_reason: FailureReason
    subscription_status: str
    reliability_band: str
    recovered: bool
    source: str


@dataclass(frozen=True)
class HistoricalLearningEvidence:
    """The comparable observations behind one learned probability."""

    cohort: str
    synthetic_samples: int
    synthetic_successes: int
    verified_samples: int
    verified_successes: int
    total_samples: int
    success_rate: float | None
    statement: str


@dataclass(frozen=True)
class LearnedPrediction:
    """A bounded learned probability alongside its evidence and fallback state."""

    probability: float
    confidence: float
    model_version: str
    fallback_used: bool
    fallback_reason: str | None
    evidence: HistoricalLearningEvidence
    factors: tuple[ScoringFactor, ...]


@dataclass(frozen=True)
class ModelTrainingSummary:
    """Provenance for an on-demand bounded model fit."""

    model_version: str
    training_samples: int
    synthetic_samples: int
    verified_outcome_samples: int
    bounded_window: str
    fallback_used: bool
    fallback_reason: str | None


@dataclass(frozen=True)
class AdaptiveStrategy:
    """One production candidate evaluated by deterministic and learned scores."""

    action: ActionType
    is_candidate: bool
    is_production_selected: bool
    is_adaptive_recommended: bool
    deterministic_probability: float
    learned_probability: float
    probability_delta: float
    deterministic_confidence: float
    model_confidence: float
    deterministic_breakdown: ExpectedValueBreakdown
    adaptive_breakdown: ExpectedValueBreakdown
    risk_level: RiskLevel
    policy: PolicyResult
    historical_evidence: HistoricalLearningEvidence
    learning_factors: tuple[ScoringFactor, ...]
    rejected_reason: str
    simulated_would_recover: bool
    simulation_basis: str


@dataclass(frozen=True)
class CounterfactualArm:
    """One arm of a read-only synthetic counterfactual."""

    label: str
    action: ActionType | None
    policy: PolicyResult | None
    probability: float
    expected_recovery_value: int
    projected_recovered: int
    simulated_would_recover: bool
    simulation_basis: str


@dataclass(frozen=True)
class CounterfactualComparison:
    """Baseline RETRY_NOW versus the advisory adaptive recommendation."""

    basis: str
    baseline: CounterfactualArm
    revivepay: CounterfactualArm
    projected_recovered_uplift: int
    projected_recovered_uplift_pct: float | None
    expected_recovery_value_uplift: int
    notice: str


@dataclass(frozen=True)
class RecoveryIntelligence:
    """The complete read-only Phase 3 evidence payload for one case."""

    case_id: str
    payment_id: str
    amount: int
    currency: str
    failure_detected: str
    diagnosis: AgentDiagnosis
    model: ModelTrainingSummary
    production_selected_action: ActionType | None
    adaptive_recommended_action: ActionType | None
    adaptive_reasoning: str
    candidates: tuple[AdaptiveStrategy, ...]
    counterfactual: CounterfactualComparison


class StructuredDiagnosisAgent:
    """Local structured diagnosis agent with a deterministic fallback.

    There is intentionally no external model or prompt in the synthetic MVP.  The
    agent consumes a bounded feature projection and turns the deterministic cause
    into a reviewer-friendly root-cause, severity, customer-context, and reasoning
    record.  Keeping this wrapper separate means a future schema-constrained AI
    provider can replace it without changing the workflow or the wire contract.
    """

    version = "structured-diagnosis-agent-v1"

    def __init__(self, diagnoser: DiagnosisEngine | None = None) -> None:
        self._diagnoser = diagnoser or RuleBasedDiagnosisEngine()
        self._fallback = RuleBasedDiagnosisEngine()

    def analyze(
        self,
        context: RecoveryContext,
        *,
        recommended_action: ActionType | None,
        high_value_threshold: int,
    ) -> AgentDiagnosis:
        try:
            diagnosis = self._diagnoser.diagnose(context)
            customer = self._customer_context(context)
            return AgentDiagnosis(
                root_cause=diagnosis.failure_reason.value,
                severity=self._severity(context, diagnosis, high_value_threshold),
                customer_context=customer,
                recommended_recovery_approach=(
                    recommended_action.value if recommended_action is not None else None
                ),
                reasoning=(
                    f"{diagnosis.explanation} {customer.summary} "
                    "The recommendation remains advisory until the unchanged "
                    "policy gate approves a live workflow action."
                ),
                source=self.version,
                fallback_used=False,
                fallback_reason=None,
            )
        except Exception as error:  # noqa: BLE001 - safe, explicit fallback boundary
            diagnosis = self._fallback.diagnose(context)
            customer = self._customer_context(context)
            return AgentDiagnosis(
                root_cause=diagnosis.failure_reason.value,
                severity=self._severity(context, diagnosis, high_value_threshold),
                customer_context=customer,
                recommended_recovery_approach=(
                    recommended_action.value if recommended_action is not None else None
                ),
                reasoning=f"{diagnosis.explanation} {customer.summary}",
                source="deterministic_diagnosis_fallback",
                fallback_used=True,
                fallback_reason=(
                    "Structured diagnosis was unavailable; the deterministic diagnosis "
                    f"was used instead ({type(error).__name__})."
                ),
            )

    @staticmethod
    def _severity(
        context: RecoveryContext, diagnosis: Diagnosis, high_value_threshold: int
    ) -> str:
        if diagnosis.requires_escalation or context.amount >= high_value_threshold:
            return "HIGH"
        if context.attempt_count > 1 or not context.customer.history_available:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _customer_context(context: RecoveryContext) -> CustomerIntelligenceContext:
        customer = context.customer
        successful_actions = tuple(sorted(item.value for item in context.succeeded_action_types))
        if not customer.history_available:
            summary = (
                "No prior customer payment history is available, so the system keeps "
                "confidence bounded and relies on the synthetic baseline."
            )
        else:
            summary = (
                f"Comparable customer cohort: {customer.subscription_status.value.lower()} "
                f"subscription, {customer.success_rate:.0%} historical payment success "
                f"across {customer.total_payments} prior payment(s)."
            )
        return CustomerIntelligenceContext(
            history_available=customer.history_available,
            total_payments=customer.total_payments,
            success_rate=customer.success_rate,
            subscription_status=customer.subscription_status.value,
            is_returning_customer=context.is_returning_customer,
            successful_recovery_actions=successful_actions,
            summary=summary,
        )


class BoundedRecoveryProbabilityModel:
    """A deterministic empirical-Bayes calibrator over bounded synthetic evidence.

    The deterministic scorer remains the prior.  Matching synthetic simulator
    projections and independently verified historical outcomes adjust that prior
    with a fixed pseudo-count, preventing a single new outcome from changing the
    model materially.  No state is persisted or updated online.
    """

    def __init__(
        self,
        session: Session,
        clock: VirtualClock,
        settings: Settings,
        *,
        exclude_case_id: str | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._settings = settings
        self._exclude_case_id = exclude_case_id
        self._builder = RecoveryContextBuilder(session, clock)
        self._diagnoser = RuleBasedDiagnosisEngine()
        self._generator = RecoveryActionCandidateGenerator()
        self._simulator = PaymentSimulatorExecutor(session=session, settings=settings, clock=clock)
        self._samples = tuple(self._synthetic_samples()) + tuple(self._verified_samples())

    @property
    def summary(self) -> ModelTrainingSummary:
        synthetic = sum(sample.source == "synthetic_simulator_projection" for sample in self._samples)
        verified = sum(sample.source == "verified_outcome" for sample in self._samples)
        fallback = not self._samples
        return ModelTrainingSummary(
            model_version=MODEL_VERSION,
            training_samples=len(self._samples),
            synthetic_samples=synthetic,
            verified_outcome_samples=verified,
            bounded_window=(
                f"up to {MAX_SYNTHETIC_CASES} synthetic cases and the most recent "
                f"{MAX_VERIFIED_OUTCOMES} verified outcomes"
            ),
            fallback_used=fallback,
            fallback_reason=(
                "No bounded synthetic or verified outcome samples were available; "
                "the deterministic scorer remains the prediction source."
                if fallback
                else None
            ),
        )

    def predict(
        self,
        context: RecoveryContext,
        action: ActionType,
        deterministic: PredictionResult,
    ) -> LearnedPrediction:
        matches = self._matching_samples(context, action)
        synthetic = [sample for sample in matches if sample.source == "synthetic_simulator_projection"]
        verified = [sample for sample in matches if sample.source == "verified_outcome"]
        total = len(matches)
        successes = sum(sample.recovered for sample in matches)

        if total == 0:
            evidence = HistoricalLearningEvidence(
                cohort=self._cohort_label(context),
                synthetic_samples=0,
                synthetic_successes=0,
                verified_samples=0,
                verified_successes=0,
                total_samples=0,
                success_rate=None,
                statement=(
                    "No comparable bounded samples were available; the learned model "
                    "retains the deterministic scorer as its fallback."
                ),
            )
            return LearnedPrediction(
                probability=deterministic.probability,
                confidence=deterministic.confidence,
                model_version=f"{MODEL_VERSION}:deterministic-fallback",
                fallback_used=True,
                fallback_reason="No matching bounded training samples.",
                evidence=evidence,
                factors=(
                    ScoringFactor(
                        name="deterministic_fallback",
                        value=round(deterministic.probability, 4),
                        influence=1.0,
                        description="No comparable learned samples were available.",
                    ),
                ),
            )

        posterior = (successes + PRIOR_STRENGTH * deterministic.probability) / (
            total + PRIOR_STRENGTH
        )
        probability = round(min(max(posterior, 0.0), 1.0), 4)
        verified_successes = sum(sample.recovered for sample in verified)
        synthetic_successes = sum(sample.recovered for sample in synthetic)
        historical_statement = self._historical_statement(
            context,
            action,
            verified_successes=verified_successes,
            verified_total=len(verified),
            synthetic_total=len(synthetic),
        )
        evidence = HistoricalLearningEvidence(
            cohort=self._cohort_label(context),
            synthetic_samples=len(synthetic),
            synthetic_successes=synthetic_successes,
            verified_samples=len(verified),
            verified_successes=verified_successes,
            total_samples=total,
            success_rate=round(successes / total, 4),
            statement=historical_statement,
        )
        confidence = min(
            0.95,
            round(
                0.30 + min(log1p(total) / 4.0, 0.45) + (0.12 if verified else 0.0),
                4,
            ),
        )
        return LearnedPrediction(
            probability=probability,
            confidence=confidence,
            model_version=MODEL_VERSION,
            fallback_used=False,
            fallback_reason=None,
            evidence=evidence,
            factors=(
                ScoringFactor(
                    name="deterministic_prior",
                    value=round(deterministic.probability, 4),
                    influence=1.0,
                    description=(
                        "The existing deterministic scorer supplies a fixed prior so "
                        "limited history cannot dominate the prediction."
                    ),
                ),
                ScoringFactor(
                    name="synthetic_simulator_samples",
                    value=f"{synthetic_successes}/{len(synthetic)}",
                    influence=round((synthetic_successes / len(synthetic)) if synthetic else 1.0, 4),
                    description=(
                        "Read-only outcomes from the seeded payment simulator; these are "
                        "synthetic training labels, not real payment data."
                    ),
                ),
                ScoringFactor(
                    name="verified_historical_outcomes",
                    value=f"{verified_successes}/{len(verified)}",
                    influence=round((verified_successes / len(verified)) if verified else 1.0, 4),
                    description=(
                        "Only independently verified recovery outcomes are included; "
                        "executor-reported success is never used as a label."
                    ),
                ),
            ),
        )

    def _synthetic_samples(self) -> Iterable[TrainingSample]:
        statement = select(RecoveryCase).order_by(RecoveryCase.created_at, RecoveryCase.case_id)
        if self._exclude_case_id:
            statement = statement.where(RecoveryCase.case_id != self._exclude_case_id)
        cases = self._session.execute(statement.limit(MAX_SYNTHETIC_CASES)).scalars().all()

        for case in cases:
            try:
                live = self._builder.build(case)
                context = context_at_detection(case, live)
                diagnosis = self._diagnoser.diagnose(context)
                for action in self._generator.generate(context, diagnosis):
                    if action in ActionType.terminal_actions():
                        continue
                    recovered, _ = self._simulator.predict_outcome(
                        context.failure_reason,
                        action,
                        context.payment_id,
                        context.attempt_count + 1,
                    )
                    yield TrainingSample(
                        action=action,
                        failure_reason=context.failure_reason,
                        subscription_status=context.customer.subscription_status.value,
                        reliability_band=self._reliability_band(context),
                        recovered=recovered,
                        source="synthetic_simulator_projection",
                    )
            except RecordNotFound:
                # A partial synthetic dataset should not make a read-only panel fail.
                continue

    def _verified_samples(self) -> Iterable[TrainingSample]:
        statement = (
            select(RecoveryAction, RecoveryOutcome, RecoveryCase, Payment, Customer)
            .join(RecoveryOutcome, RecoveryOutcome.action_id == RecoveryAction.action_id)
            .join(RecoveryCase, RecoveryCase.case_id == RecoveryAction.case_id)
            .join(Payment, Payment.payment_id == RecoveryAction.payment_id)
            .outerjoin(Customer, Customer.customer_id == Payment.customer_id)
            .order_by(RecoveryOutcome.verification_timestamp.desc(), RecoveryAction.action_id.desc())
            .limit(MAX_VERIFIED_OUTCOMES)
        )
        for action, outcome, case, _payment, customer in self._session.execute(statement).all():
            if action.action_type in ActionType.terminal_actions():
                continue
            reason = self._reason_for(case, outcome)
            success_rate = customer.historical_success_rate if customer is not None else None
            subscription = (
                customer.subscription_status.value
                if customer is not None
                else SubscriptionStatus.NONE.value
            )
            yield TrainingSample(
                action=action.action_type,
                failure_reason=reason,
                subscription_status=subscription,
                reliability_band=self._reliability_band_from_rate(success_rate),
                recovered=bool(outcome.recovered),
                source="verified_outcome",
            )

    def _matching_samples(
        self, context: RecoveryContext, action: ActionType
    ) -> list[TrainingSample]:
        action_samples = [sample for sample in self._samples if sample.action is action]
        action_reason = [
            sample
            for sample in action_samples
            if sample.failure_reason is context.failure_reason
        ]
        exact = [
            sample
            for sample in action_reason
            if sample.subscription_status == context.customer.subscription_status.value
            and sample.reliability_band == self._reliability_band(context)
        ]
        return exact or action_reason or action_samples

    @staticmethod
    def _reason_for(case: RecoveryCase, outcome: RecoveryOutcome) -> FailureReason:
        candidate = (case.diagnosis or {}).get("failure_reason")
        candidate = candidate or (outcome.failure_reason.value if outcome.failure_reason else None)
        try:
            return FailureReason(str(candidate)) if candidate else FailureReason.UNKNOWN
        except ValueError:
            return FailureReason.UNKNOWN

    @staticmethod
    def _reliability_band(context: RecoveryContext) -> str:
        if not context.customer.history_available:
            return "NO_HISTORY"
        return BoundedRecoveryProbabilityModel._reliability_band_from_rate(
            context.customer.success_rate
        )

    @staticmethod
    def _reliability_band_from_rate(success_rate: float | None) -> str:
        if success_rate is None:
            return "NO_HISTORY"
        if success_rate >= 0.80:
            return "RELIABLE"
        if success_rate >= 0.50:
            return "MIXED"
        return "FRAGILE"

    def _cohort_label(self, context: RecoveryContext) -> str:
        return (
            f"{context.customer.subscription_status.value.lower()} subscription / "
            f"{self._reliability_band(context).lower()} payment history / "
            f"{context.failure_reason.value.lower()} failure"
        )

    def _historical_statement(
        self,
        context: RecoveryContext,
        action: ActionType,
        *,
        verified_successes: int,
        verified_total: int,
        synthetic_total: int,
    ) -> str:
        if verified_total:
            return (
                f"For the comparable {self._cohort_label(context)} cohort, verified "
                f"{action.value} recovery succeeded {verified_successes}/{verified_total} "
                "times in the bounded historical window."
            )
        return (
            "No comparable verified outcomes are available yet; this calibration uses "
            f"{synthetic_total} bounded synthetic simulator projection(s) plus the "
            "deterministic scorer prior."
        )


def context_at_detection(case: RecoveryCase, live: RecoveryContext) -> RecoveryContext:
    """Reconstruct a stable, read-only detection-time context.

    Counterfactual and training projections must not silently collapse once a live
    case is terminal.  This mirrors the existing Strategy Lab semantics while
    staying local to the advisory layer: recovery history is cleared, the original
    at-risk amount/reason are retained, and no persistence is modified.
    """

    executed = sum(1 for action in case.actions if action.executed_at is not None)
    attempts_at_detection = max(int(live.attempt_count) - executed, 1)
    reason_value = (case.diagnosis or {}).get("failure_reason")
    try:
        reason = FailureReason(str(reason_value)) if reason_value else live.failure_reason
    except ValueError:
        reason = live.failure_reason

    return replace(
        live,
        amount=int(case.amount_at_risk),
        failure_reason=reason,
        attempt_count=attempts_at_detection,
        payment_status=PaymentStatus.FAILED,
        previous_recovery_attempt_count=0,
        attempted_action_types=frozenset(),
        succeeded_action_types=frozenset(),
        failed_action_types=frozenset(),
        unsuccessful_outcome_count=0,
        scheduled_at=None,
        pending_action_id=None,
    )


class RecoveryIntelligenceService:
    """Compose explainable Phase 3 evidence for a case without mutating it."""

    def __init__(
        self,
        session: Session,
        clock: VirtualClock,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._settings = settings or get_settings()
        self._builder = RecoveryContextBuilder(session, clock)
        self._diagnoser = RuleBasedDiagnosisEngine()
        self._generator = RecoveryActionCandidateGenerator()

    def evaluate(
        self,
        case_id: str,
        overrides: ScenarioOverrides | None = None,
    ) -> RecoveryIntelligence:
        """Return advisory diagnosis, learned comparisons, and counterfactuals."""

        case = self._session.get(RecoveryCase, case_id)
        if case is None:
            raise RecordNotFound("RecoveryCase", case_id)
        payment = self._session.get(Payment, case.payment_id)
        if payment is None:
            raise RecordNotFound("Payment", case.payment_id)

        effective = (overrides or ScenarioOverrides()).apply(self._settings)
        live_context = self._builder.build(case)
        context = context_at_detection(case, live_context)
        diagnosis = self._diagnoser.diagnose(context)
        candidates = self._generator.generate(context, diagnosis)

        simulator = PaymentSimulatorExecutor(
            session=self._session, settings=effective, clock=self._clock
        )
        calculator = ExpectedRecoveryCalculator(effective)
        scorer = DeterministicRecoveryScorer()
        engine = RecoveryDecisionEngine(
            predictor=scorer, calculator=calculator, settings=effective
        )
        policy_engine = PolicyEngine(
            settings=effective, supported_actions=simulator.supported_actions
        )
        production_decision = engine.decide(context, diagnosis, candidates)
        learner = BoundedRecoveryProbabilityModel(
            self._session,
            self._clock,
            effective,
            exclude_case_id=case.case_id,
        )

        scored = [
            self._score_action(
                action=action,
                is_candidate=True,
                context=context,
                diagnosis=diagnosis,
                payment=payment,
                engine=engine,
                policy_engine=policy_engine,
                calculator=calculator,
                learner=learner,
                simulator=simulator,
                production_selected=production_decision.selected_action,
            )
            for action in candidates
        ]
        adaptive_action = self._adaptive_action(scored)
        with_reasons = self._apply_selection_reasons(scored, adaptive_action)
        diagnosis_agent = StructuredDiagnosisAgent().analyze(
            context,
            recommended_action=adaptive_action,
            high_value_threshold=effective.high_value_escalation_threshold,
        )
        counterfactual = self._counterfactual(
            context=context,
            diagnosis=diagnosis,
            payment=payment,
            engine=engine,
            policy_engine=policy_engine,
            calculator=calculator,
            learner=learner,
            simulator=simulator,
            adaptive_action=adaptive_action,
            existing=with_reasons,
        )

        return RecoveryIntelligence(
            case_id=case.case_id,
            payment_id=payment.payment_id,
            amount=int(case.amount_at_risk),
            currency=payment.currency,
            failure_detected=context.failure_reason.value,
            diagnosis=diagnosis_agent,
            model=learner.summary,
            production_selected_action=production_decision.selected_action,
            adaptive_recommended_action=adaptive_action,
            adaptive_reasoning=self._adaptive_reasoning(with_reasons, adaptive_action, payment.currency),
            candidates=tuple(with_reasons),
            counterfactual=counterfactual,
        )

    def _score_action(
        self,
        *,
        action: ActionType,
        is_candidate: bool,
        context: RecoveryContext,
        diagnosis: Diagnosis,
        payment: Payment,
        engine: RecoveryDecisionEngine,
        policy_engine: PolicyEngine,
        calculator: ExpectedRecoveryCalculator,
        learner: BoundedRecoveryProbabilityModel,
        simulator: PaymentSimulatorExecutor,
        production_selected: ActionType | None,
    ) -> AdaptiveStrategy:
        deterministic_decision = engine.decide(context, diagnosis, [action])
        deterministic = deterministic_decision.selected
        if deterministic is None:  # pragma: no cover - one candidate always scores
            raise RuntimeError("One-candidate decision did not produce a scored candidate.")
        policy = policy_engine.evaluate(context, deterministic_decision)
        learned = learner.predict(context, action, deterministic.prediction)
        adaptive_breakdown = calculator.calculate(
            amount=context.amount,
            probability=learned.probability,
            action=action,
        )

        would_recover = False
        basis = "not_applicable"
        if policy.outcome is PolicyOutcome.APPROVED and action not in ActionType.terminal_actions():
            would_recover, metadata = simulator.predict_outcome(
                context.failure_reason,
                action,
                payment.payment_id,
                context.attempt_count + 1,
            )
            basis = str(metadata.get("decision_basis", "synthetic_simulator_projection"))
        elif action in ActionType.terminal_actions():
            basis = "terminal_disposition_no_payment_attempt"
        else:
            basis = "policy_prevented_simulation"

        return AdaptiveStrategy(
            action=action,
            is_candidate=is_candidate,
            is_production_selected=action is production_selected,
            is_adaptive_recommended=False,
            deterministic_probability=deterministic.probability,
            learned_probability=learned.probability,
            probability_delta=round(learned.probability - deterministic.probability, 4),
            deterministic_confidence=deterministic.confidence,
            model_confidence=learned.confidence,
            deterministic_breakdown=deterministic.breakdown,
            adaptive_breakdown=adaptive_breakdown,
            risk_level=deterministic.risk_level,
            policy=policy,
            historical_evidence=learned.evidence,
            learning_factors=learned.factors,
            rejected_reason="",
            simulated_would_recover=would_recover,
            simulation_basis=basis,
        )

    @staticmethod
    def _adaptive_action(options: list[AdaptiveStrategy]) -> ActionType | None:
        eligible = [
            option
            for option in options
            if option.policy.outcome is PolicyOutcome.APPROVED
        ]
        if not eligible:
            return None
        declaration_order = {action: index for index, action in enumerate(ActionType)}
        return max(
            eligible,
            key=lambda option: (
                option.adaptive_breakdown.expected_recovery_value,
                option.learned_probability,
                -option.adaptive_breakdown.intervention_cost,
                -declaration_order[option.action],
            ),
        ).action

    @staticmethod
    def _apply_selection_reasons(
        options: list[AdaptiveStrategy],
        recommended: ActionType | None,
    ) -> list[AdaptiveStrategy]:
        winner = next((option for option in options if option.action is recommended), None)
        enriched: list[AdaptiveStrategy] = []
        for option in options:
            if option.policy.outcome is not PolicyOutcome.APPROVED:
                reason = (
                    f"Rejected by policy ({option.policy.outcome.value}): "
                    f"{option.policy.reason}"
                )
            elif option.action is recommended:
                reason = (
                    "Selected by the bounded advisory model because it has the highest "
                    "policy-eligible adaptive expected recovery value."
                )
            elif winner is not None:
                delta = (
                    winner.adaptive_breakdown.expected_recovery_value
                    - option.adaptive_breakdown.expected_recovery_value
                )
                reason = (
                    f"Rejected: adaptive expected recovery is {delta} minor units below "
                    f"{winner.action.value}."
                )
            else:
                reason = "No policy-approved adaptive recommendation is available."
            enriched.append(
                replace(
                    option,
                    is_adaptive_recommended=option.action is recommended,
                    rejected_reason=reason,
                )
            )
        return enriched

    def _counterfactual(
        self,
        *,
        context: RecoveryContext,
        diagnosis: Diagnosis,
        payment: Payment,
        engine: RecoveryDecisionEngine,
        policy_engine: PolicyEngine,
        calculator: ExpectedRecoveryCalculator,
        learner: BoundedRecoveryProbabilityModel,
        simulator: PaymentSimulatorExecutor,
        adaptive_action: ActionType | None,
        existing: list[AdaptiveStrategy],
    ) -> CounterfactualComparison:
        baseline_option = next(
            (option for option in existing if option.action is ActionType.RETRY_NOW),
            None,
        )
        if baseline_option is None:
            baseline_option = self._score_action(
                action=ActionType.RETRY_NOW,
                is_candidate=False,
                context=context,
                diagnosis=diagnosis,
                payment=payment,
                engine=engine,
                policy_engine=policy_engine,
                calculator=calculator,
                learner=learner,
                simulator=simulator,
                production_selected=None,
            )

        selected_option = next(
            (option for option in existing if option.action is adaptive_action),
            None,
        )
        baseline = self._counterfactual_arm("Baseline", baseline_option, context.amount)
        revivepay = self._counterfactual_arm("RevivePay advisory", selected_option, context.amount)
        uplift = revivepay.projected_recovered - baseline.projected_recovered
        uplift_pct = (
            round(uplift / baseline.projected_recovered * 100, 2)
            if baseline.projected_recovered
            else (100.0 if uplift > 0 else None)
        )
        return CounterfactualComparison(
            basis="detection_time_synthetic_projection",
            baseline=baseline,
            revivepay=revivepay,
            projected_recovered_uplift=uplift,
            projected_recovered_uplift_pct=uplift_pct,
            expected_recovery_value_uplift=(
                revivepay.expected_recovery_value - baseline.expected_recovery_value
            ),
            notice=(
                "Synthetic simulator projection only. Both arms use the same "
                "detection-time context and policy engine; no real payment was "
                "attempted and no real financial result is implied."
            ),
        )

    @staticmethod
    def _counterfactual_arm(
        label: str,
        option: AdaptiveStrategy | None,
        amount: int,
    ) -> CounterfactualArm:
        if option is None:
            return CounterfactualArm(
                label=label,
                action=None,
                policy=None,
                probability=0.0,
                expected_recovery_value=0,
                projected_recovered=0,
                simulated_would_recover=False,
                simulation_basis="no_policy_approved_adaptive_action",
            )
        projected = amount if option.simulated_would_recover else 0
        return CounterfactualArm(
            label=label,
            action=option.action,
            policy=option.policy,
            probability=option.learned_probability,
            expected_recovery_value=option.adaptive_breakdown.expected_recovery_value,
            projected_recovered=projected,
            simulated_would_recover=option.simulated_would_recover,
            simulation_basis=option.simulation_basis,
        )

    @staticmethod
    def _adaptive_reasoning(
        options: list[AdaptiveStrategy],
        recommended: ActionType | None,
        currency: str,
    ) -> str:
        if recommended is None:
            return (
                "The advisory model found no policy-approved production candidate. "
                "The deterministic workflow and policy gate remain authoritative."
            )
        winner = next(option for option in options if option.action is recommended)
        return (
            f"The bounded advisory model evaluated {len(options)} production candidate(s) "
            f"and recommends {recommended.value}: learned recovery probability "
            f"{winner.learned_probability:.1%}, adaptive expected recovery "
            f"{winner.adaptive_breakdown.expected_recovery_value} {currency} minor units, "
            "after policy eligibility. This is read-only advice; live execution still "
            "uses the configured deterministic workflow and mandatory policy gate."
        )


__all__ = [
    "AdaptiveStrategy",
    "AgentDiagnosis",
    "BoundedRecoveryProbabilityModel",
    "CounterfactualComparison",
    "CounterfactualArm",
    "CustomerIntelligenceContext",
    "HistoricalLearningEvidence",
    "LearnedPrediction",
    "ModelTrainingSummary",
    "RecoveryIntelligence",
    "RecoveryIntelligenceService",
    "StructuredDiagnosisAgent",
    "context_at_detection",
]
