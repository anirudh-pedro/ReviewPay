"""Strategy Lab: what-if comparison and baseline benchmarking.

Answers the question a judge actually asks: *why that action and not another one?*

Both features here are read-only projections over the real engine. Every
probability comes from the deterministic scorer, every valuation from the single
expected-recovery-value calculator, and every eligibility verdict from the real
policy engine with its real rule set. Nothing is recomputed, and no payment state
changes — a what-if must never move money.

Parameter overrides work by building a modified ``Settings`` and handing it to the
same components. That is what lets the UI offer "what if the retry limit were 4?"
without a second implementation of policy anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, replace as dataclass_replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings, get_settings
from app.core.enums import ActionType, FailureReason, PaymentStatus, PolicyOutcome
from app.core.errors import RecordNotFound
from app.core.logging import get_logger
from app.integrations.payment_simulator import PaymentSimulatorExecutor
from app.ml.deterministic_scorer import DeterministicRecoveryScorer
from app.models import Payment, RecoveryCase
from app.services.candidate_generator import RecoveryActionCandidateGenerator
from app.services.context_builder import RecoveryContext, RecoveryContextBuilder
from app.services.decision_engine import RecoveryDecisionEngine
from app.services.diagnosis_engine import Diagnosis, RuleBasedDiagnosisEngine
from app.services.expected_value import ExpectedRecoveryCalculator
from app.services.policy_engine import PolicyEngine

logger = get_logger("strategy_lab")

#: Actions offered for comparison. Terminal dispositions are excluded because
#: neither attempts recovery, so comparing their expected value is meaningless.
COMPARABLE_ACTIONS: tuple[ActionType, ...] = (
    ActionType.RETRY_NOW,
    ActionType.RETRY_LATER,
    ActionType.SEND_PAYMENT_LINK,
    ActionType.SEND_REMINDER,
    ActionType.CHANGE_PAYMENT_METHOD,
    ActionType.ESCALATE_HUMAN,
)


@dataclass(frozen=True)
class ScenarioOverrides:
    """Optional parameter adjustments for a what-if run.

    Every field maps onto an existing setting, so an override changes the same
    value the production engine reads.
    """

    retry_later_delay_minutes: int | None = None
    max_automatic_retries: int | None = None
    repeated_failure_limit: int | None = None
    high_value_escalation_threshold: int | None = None
    intervention_cost_minor: dict[str, int] | None = None
    friction_penalty_minor: dict[str, int] | None = None

    def apply(self, settings: Settings) -> Settings:
        """Return a settings copy with the overrides applied."""
        changes: dict[str, Any] = {}

        if self.retry_later_delay_minutes is not None:
            changes["retry_later_delay_minutes"] = self.retry_later_delay_minutes
        if self.max_automatic_retries is not None:
            changes["max_automatic_retries"] = self.max_automatic_retries
        if self.repeated_failure_limit is not None:
            changes["repeated_failure_limit"] = self.repeated_failure_limit
        if self.high_value_escalation_threshold is not None:
            changes["high_value_escalation_threshold"] = (
                self.high_value_escalation_threshold
            )
        if self.intervention_cost_minor:
            changes["intervention_cost_minor"] = {
                **settings.intervention_cost_minor,
                **self.intervention_cost_minor,
            }
        if self.friction_penalty_minor:
            changes["friction_penalty_minor"] = {
                **settings.friction_penalty_minor,
                **self.friction_penalty_minor,
            }

        if not changes:
            return settings
        return settings.model_copy(update=changes)

    @property
    def is_empty(self) -> bool:
        return not any(
            value is not None
            for value in (
                self.retry_later_delay_minutes,
                self.max_automatic_retries,
                self.repeated_failure_limit,
                self.high_value_escalation_threshold,
                self.intervention_cost_minor,
                self.friction_penalty_minor,
            )
        )


@dataclass(frozen=True)
class StrategyOption:
    """One candidate strategy, fully valued and policy-checked."""

    action: str
    probability: float
    confidence: float
    intervention_cost: int
    friction_penalty: int
    gross_expected_recovery: int
    expected_recovery_value: int
    risk_level: str
    policy_outcome: str
    policy_rule_id: str
    policy_reason: str
    eligible: bool
    is_candidate: bool
    is_recommended: bool
    is_current: bool
    simulated_would_succeed: bool
    simulation_basis: str
    scoring_factors: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class CustomerContext:
    """Behavioural context shown alongside the strategies."""

    customer_id: str
    total_payments: int
    successful_payments: int
    failed_payments: int
    success_rate: float
    average_transaction_value: int
    subscription_status: str
    history_available: bool
    is_returning_customer: bool
    days_since_previous_payment: int | None
    previous_recovery_attempts: int
    attempted_actions: tuple[str, ...]
    failed_actions: tuple[str, ...]
    succeeded_actions: tuple[str, ...]


@dataclass(frozen=True)
class StrategyLabResult:
    """A complete what-if comparison for one case."""

    case_id: str
    payment_id: str
    amount: int
    currency: str
    payment_method: str
    failure_reason: str
    attempt_count: int
    case_state: str
    diagnosis: dict[str, Any]
    customer: CustomerContext
    options: tuple[StrategyOption, ...]
    recommended_action: str | None
    current_action: str | None
    recommendation_reason: str
    overrides_applied: bool
    effective_settings: dict[str, Any]
    model_version: str
    data_source: str = "synthetic_simulation"


@dataclass(frozen=True)
class StrategyComparison:
    """Baseline strategy against RevivePay's expected-value selection."""

    strategy: str
    description: str
    cases: int
    amount_at_risk: int
    expected_recovery_value: int
    projected_recovered: int
    projected_recovery_rate: float
    cases_projected_recovered: int
    cases_blocked: int
    cases_escalated: int
    escalation_rate: float
    actions_used: dict[str, int]


@dataclass(frozen=True)
class BaselineComparison:
    """The measurable-impact benchmark.

    Both arms are computed with the same scorer, the same valuation, the same policy
    engine, and the same deterministic simulator. The only difference is the
    selection rule, which is the point of the comparison.
    """

    baseline: StrategyComparison
    revivepay: StrategyComparison
    recovered_uplift: int
    recovered_uplift_pct: float
    recovery_rate_uplift_pct: float
    expected_value_uplift: int
    currency: str
    cases_evaluated: int
    notice: str = (
        "Synthetic simulation benchmark. Both strategies are evaluated against the "
        "same seeded simulator over synthetic payments. These figures do not "
        "describe real payment recovery."
    )
    data_source: str = "synthetic_simulation"


class StrategyLabService:
    """Read-only what-if evaluation and baseline benchmarking."""

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
        self._predictor = DeterministicRecoveryScorer()
        self._simulator = PaymentSimulatorExecutor(
            session=session, settings=self._settings, clock=clock
        )

    # -- what-if -----------------------------------------------------------

    def evaluate(
        self, case_id: str, overrides: ScenarioOverrides | None = None
    ) -> StrategyLabResult:
        """Value every comparable strategy for a case."""
        case = self._session.get(RecoveryCase, case_id)
        if case is None:
            raise RecordNotFound("RecoveryCase", case_id)

        payment = self._session.get(Payment, case.payment_id)
        if payment is None:
            raise RecordNotFound("Payment", case.payment_id)

        overrides = overrides or ScenarioOverrides()
        effective = overrides.apply(self._settings)

        context = self._builder.build(case)
        diagnosis = self._diagnoser.diagnose(context)
        candidates = self._generator.generate(context, diagnosis)

        calculator = ExpectedRecoveryCalculator(effective)
        engine = RecoveryDecisionEngine(
            predictor=self._predictor, calculator=calculator, settings=effective
        )
        policy = PolicyEngine(
            settings=effective, supported_actions=self._simulator.supported_actions
        )

        current_action = self._current_action(case)
        options = self._score_all(
            context=context,
            diagnosis=diagnosis,
            candidates=candidates,
            engine=engine,
            policy=policy,
            payment=payment,
            current_action=current_action,
        )

        recommended = self._recommend(options)
        options = tuple(
            dataclass_replace(option, is_recommended=option.action == recommended)
            for option in options
        )

        logger.info(
            "strategy lab | case=%s | recommended=%s | overrides=%s",
            case_id,
            recommended,
            not overrides.is_empty,
        )

        return StrategyLabResult(
            case_id=case.case_id,
            payment_id=payment.payment_id,
            amount=int(payment.amount),
            currency=payment.currency,
            payment_method=payment.payment_method.value,
            failure_reason=context.failure_reason.value,
            attempt_count=context.attempt_count,
            case_state=case.state.value,
            diagnosis=diagnosis.to_dict(),
            customer=self._customer_context(context),
            options=options,
            recommended_action=recommended,
            current_action=current_action,
            recommendation_reason=self._reason(options, recommended, payment.currency),
            overrides_applied=not overrides.is_empty,
            effective_settings={
                "retry_later_delay_minutes": effective.retry_later_delay_minutes,
                "max_automatic_retries": effective.max_automatic_retries,
                "repeated_failure_limit": effective.repeated_failure_limit,
                "high_value_escalation_threshold": (
                    effective.high_value_escalation_threshold
                ),
            },
            model_version=self._predictor.model_version,
        )

    def _score_all(
        self,
        *,
        context: RecoveryContext,
        diagnosis: Diagnosis,
        candidates: list[ActionType],
        engine: RecoveryDecisionEngine,
        policy: PolicyEngine,
        payment: Payment,
        current_action: str | None,
    ) -> tuple[StrategyOption, ...]:
        """Score every comparable action, not only the generated candidates.

        The generator narrows to what is plausible; the lab deliberately shows the
        rejected options too, because "why not RETRY_NOW?" is the question being
        answered.
        """
        options: list[StrategyOption] = []

        for action in COMPARABLE_ACTIONS:
            # One-action decision so the real engine produces the valuation and the
            # real policy engine judges that exact selection.
            decision = engine.decide(context, diagnosis, [action])
            verdict = policy.evaluate(context, decision)

            would_succeed, basis = self._simulator.predict_outcome(
                context.failure_reason, action, payment.payment_id, context.attempt_count + 1
            )

            breakdown = decision.breakdown
            options.append(
                StrategyOption(
                    action=action.value,
                    probability=decision.probability,
                    confidence=decision.confidence,
                    intervention_cost=breakdown.intervention_cost,
                    friction_penalty=breakdown.customer_friction_penalty,
                    gross_expected_recovery=breakdown.gross_expected_recovery,
                    expected_recovery_value=breakdown.expected_recovery_value,
                    risk_level=decision.risk_level.value,
                    policy_outcome=verdict.outcome.value,
                    policy_rule_id=verdict.rule_id,
                    policy_reason=verdict.reason,
                    eligible=verdict.outcome is PolicyOutcome.APPROVED,
                    is_candidate=action in candidates,
                    is_recommended=False,
                    is_current=current_action == action.value,
                    simulated_would_succeed=would_succeed,
                    simulation_basis=str(basis.get("decision_basis", "unknown")),
                    scoring_factors=tuple(
                        factor.to_dict()
                        for candidate in decision.ranked
                        for factor in candidate.prediction.explanation
                    ),
                )
            )

        return tuple(
            sorted(options, key=lambda option: option.expected_recovery_value, reverse=True)
        )

    @staticmethod
    def _recommend(options: tuple[StrategyOption, ...]) -> str | None:
        """Highest expected recovery value among policy-eligible options."""
        eligible = [option for option in options if option.eligible]
        if not eligible:
            return None
        return max(eligible, key=lambda option: option.expected_recovery_value).action

    @staticmethod
    def _reason(
        options: tuple[StrategyOption, ...], recommended: str | None, currency: str
    ) -> str:
        if recommended is None:
            return (
                "No strategy is currently permitted by policy, so this case must be "
                "escalated or stopped rather than recovered automatically."
            )

        winner = next(option for option in options if option.action == recommended)
        others = [option for option in options if option.action != recommended]
        runner_up = max(
            (option for option in others if option.eligible),
            key=lambda option: option.expected_recovery_value,
            default=None,
        )

        sentence = (
            f"RevivePay recommends {recommended} because it maximises expected "
            f"recoverable revenue at {winner.expected_recovery_value} {currency} minor "
            f"units while satisfying every policy rule."
        )
        if runner_up is not None:
            margin = winner.expected_recovery_value - runner_up.expected_recovery_value
            sentence += (
                f" The next permitted option, {runner_up.action}, is worth "
                f"{runner_up.expected_recovery_value}, a difference of {margin}, "
                f"driven by recovery probabilities of {winner.probability:.3f} against "
                f"{runner_up.probability:.3f}."
            )
        return sentence

    def _current_action(self, case: RecoveryCase) -> str | None:
        actions = sorted(case.actions, key=lambda item: (item.created_at, item.action_id))
        return actions[-1].action_type.value if actions else None

    @staticmethod
    def _customer_context(context: RecoveryContext) -> CustomerContext:
        customer = context.customer
        return CustomerContext(
            customer_id=customer.customer_id,
            total_payments=customer.total_payments,
            successful_payments=customer.successful_payments,
            failed_payments=customer.failed_payments,
            success_rate=customer.success_rate,
            average_transaction_value=customer.average_transaction_value,
            subscription_status=customer.subscription_status.value,
            history_available=customer.history_available,
            is_returning_customer=context.is_returning_customer,
            days_since_previous_payment=context.days_since_previous_payment,
            previous_recovery_attempts=context.previous_recovery_attempt_count,
            attempted_actions=tuple(
                sorted(item.value for item in context.attempted_action_types)
            ),
            failed_actions=tuple(sorted(item.value for item in context.failed_action_types)),
            succeeded_actions=tuple(
                sorted(item.value for item in context.succeeded_action_types)
            ),
        )

    # -- baseline benchmark ------------------------------------------------

    def baseline_comparison(self, *, limit: int | None = None) -> BaselineComparison:
        """Compare always-RETRY_NOW against expected-value selection.

        Projections use the simulator's own deterministic outcome function, so this
        is not a model of the simulator but the simulator's actual verdict for each
        hypothetical action. Read-only throughout.
        """
        cases = self._evaluable_cases(limit=limit)

        baseline = self._project(cases, strategy="baseline")
        revivepay = self._project(cases, strategy="revivepay")

        recovered_uplift = revivepay.projected_recovered - baseline.projected_recovered
        recovered_uplift_pct = (
            round(recovered_uplift / baseline.projected_recovered * 100, 2)
            if baseline.projected_recovered
            else (100.0 if recovered_uplift > 0 else 0.0)
        )

        return BaselineComparison(
            baseline=baseline,
            revivepay=revivepay,
            recovered_uplift=recovered_uplift,
            recovered_uplift_pct=recovered_uplift_pct,
            recovery_rate_uplift_pct=round(
                (revivepay.projected_recovery_rate - baseline.projected_recovery_rate) * 100,
                2,
            ),
            expected_value_uplift=(
                revivepay.expected_recovery_value - baseline.expected_recovery_value
            ),
            currency=self._settings.default_currency,
            cases_evaluated=len(cases),
        )

    def _evaluable_cases(self, *, limit: int | None) -> list[RecoveryCase]:
        """Every case, in a stable order, so the benchmark is reproducible."""
        statement = select(RecoveryCase).order_by(
            RecoveryCase.created_at.asc(), RecoveryCase.case_id.asc()
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self._session.execute(statement).scalars().all())

    def _project(self, cases: list[RecoveryCase], *, strategy: str) -> StrategyComparison:
        """Project one strategy across the given cases without mutating anything."""
        calculator = ExpectedRecoveryCalculator(self._settings)
        engine = RecoveryDecisionEngine(
            predictor=self._predictor, calculator=calculator, settings=self._settings
        )
        policy = PolicyEngine(
            settings=self._settings, supported_actions=self._simulator.supported_actions
        )

        amount_at_risk = 0
        expected_value = 0
        projected_recovered = 0
        cases_recovered = 0
        cases_blocked = 0
        cases_escalated = 0
        actions_used: dict[str, int] = {}

        for case in cases:
            payment = self._session.get(Payment, case.payment_id)
            if payment is None:
                continue

            # Evaluate each case as it stood **when first detected**, not as it
            # stands now. Without this the benchmark silently collapses to zero the
            # moment Autopilot resolves the cases: recovered payments fail the
            # invalid-state rule and exhausted ones fail the budget rule, so every
            # hypothetical action would be blocked and both arms would read zero.
            context = self._context_as_detected(case, self._builder.build(case))
            diagnosis = self._diagnoser.diagnose(context)
            amount_at_risk += int(case.amount_at_risk)

            action = self._choose(
                strategy=strategy,
                context=context,
                diagnosis=diagnosis,
                engine=engine,
                policy=policy,
            )
            if action is None:
                cases_blocked += 1
                continue

            decision = engine.decide(context, diagnosis, [action])
            verdict = policy.evaluate(context, decision)
            actions_used[action.value] = actions_used.get(action.value, 0) + 1

            if verdict.outcome is PolicyOutcome.ESCALATED:
                cases_escalated += 1
                continue
            if verdict.outcome is PolicyOutcome.BLOCKED:
                cases_blocked += 1
                continue

            expected_value += decision.expected_recovery_value

            would_succeed, _ = self._simulator.predict_outcome(
                context.failure_reason,
                action,
                payment.payment_id,
                context.attempt_count + 1,
            )
            if would_succeed:
                projected_recovered += int(payment.amount)
                cases_recovered += 1

        evaluated = len(cases)
        return StrategyComparison(
            strategy="Baseline" if strategy == "baseline" else "RevivePay",
            description=(
                "Always retry immediately, the conventional default."
                if strategy == "baseline"
                else "Select the policy-eligible action with the highest expected "
                "recovery value."
            ),
            cases=evaluated,
            amount_at_risk=amount_at_risk,
            expected_recovery_value=expected_value,
            projected_recovered=projected_recovered,
            projected_recovery_rate=(
                round(projected_recovered / amount_at_risk, 4) if amount_at_risk else 0.0
            ),
            cases_projected_recovered=cases_recovered,
            cases_blocked=cases_blocked,
            cases_escalated=cases_escalated,
            escalation_rate=round(cases_escalated / evaluated, 4) if evaluated else 0.0,
            actions_used=actions_used,
        )

    def _context_as_detected(
        self, case: RecoveryCase, live: RecoveryContext
    ) -> RecoveryContext:
        """Reconstruct the case's context as at detection time.

        Everything here comes from persisted data rather than assumption:

        - the amount is the ``amount_at_risk`` captured when the case opened
        - the cause is the persisted diagnosis
        - the attempt count is today's count minus the recovery attempts since made
        - recovery history is emptied, because at detection there was none

        The scorer, valuation, and policy engine then all do their real work against
        that reconstructed position. Customer history is left as-is because it is
        defined as the record *prior* to this payment and never mutates.
        """
        executed = sum(1 for action in case.actions if action.executed_at is not None)
        attempts_at_detection = max(int(live.attempt_count) - executed, 1)

        diagnosed = (case.diagnosis or {}).get("failure_reason")
        try:
            reason = FailureReason(diagnosed) if diagnosed else live.failure_reason
        except ValueError:
            reason = live.failure_reason

        return dataclass_replace(
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

    def _choose(
        self,
        *,
        strategy: str,
        context: RecoveryContext,
        diagnosis: Diagnosis,
        engine: RecoveryDecisionEngine,
        policy: PolicyEngine,
    ) -> ActionType | None:
        """Pick the action each strategy would take."""
        if strategy == "baseline":
            # The conventional default: retry immediately, regardless of cause.
            return ActionType.RETRY_NOW

        candidates = self._generator.generate(context, diagnosis)
        if not candidates:
            return None

        decision = engine.decide(context, diagnosis, candidates)
        return decision.selected_action


__all__ = [
    "COMPARABLE_ACTIONS",
    "BaselineComparison",
    "CustomerContext",
    "ScenarioOverrides",
    "StrategyComparison",
    "StrategyLabResult",
    "StrategyLabService",
    "StrategyOption",
]
