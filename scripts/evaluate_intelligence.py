"""Evaluate baseline, deterministic, and local-ML strategy selection fairly.

Usage:
    python scripts/evaluate_intelligence.py

The command creates a reproducible train/held-out split from already seeded
synthetic cases. All three strategies are evaluated on the same held-out cases and
use the same read-only simulator projection. No payment state, action, outcome, or
audit row is created.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.container import get_clock  # noqa: E402
from app.core.enums import ActionType, PolicyOutcome  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.integrations.payment_simulator import PaymentSimulatorExecutor  # noqa: E402
from app.ml.deterministic_scorer import DeterministicRecoveryScorer  # noqa: E402
from app.ml.local_logistic import save_artifact, train_logistic_model  # noqa: E402
from app.ml.local_model_predictor import LocalLogisticRecoveryPredictor  # noqa: E402
from app.ml.synthetic_dataset import SyntheticRecoveryDatasetBuilder  # noqa: E402
from app.models import Payment, RecoveryCase  # noqa: E402
from app.services.candidate_generator import RecoveryActionCandidateGenerator  # noqa: E402
from app.services.context_builder import RecoveryContextBuilder  # noqa: E402
from app.services.decision_engine import RecoveryDecisionEngine  # noqa: E402
from app.services.diagnosis_engine import RuleBasedDiagnosisEngine  # noqa: E402
from app.services.expected_value import ExpectedRecoveryCalculator  # noqa: E402
from app.services.policy_engine import PolicyEngine  # noqa: E402
from app.services.recovery_intelligence import context_at_detection  # noqa: E402


@dataclass(frozen=True)
class EvaluationMetrics:
    strategy: str
    cases: int
    amount_at_risk: int
    projected_recovered: int
    projected_recovery_rate: float
    expected_recovery_value: int
    blocked_cases: int
    escalated_cases: int
    stopped_cases: int
    action_distribution: dict[str, int]


def _project(session, clock, settings, cases, *, strategy: str, predictor) -> EvaluationMetrics:
    """Evaluate one selection strategy through the unchanged decision/policy seams."""

    builder = RecoveryContextBuilder(session, clock)
    diagnoser = RuleBasedDiagnosisEngine()
    generator = RecoveryActionCandidateGenerator()
    simulator = PaymentSimulatorExecutor(session=session, settings=settings, clock=clock)
    engine = RecoveryDecisionEngine(
        predictor=predictor,
        calculator=ExpectedRecoveryCalculator(settings),
        settings=settings,
    )
    policy_engine = PolicyEngine(settings=settings, supported_actions=simulator.supported_actions)
    amount_at_risk = projected_recovered = expected_value = blocked = escalated = stopped = 0
    actions: dict[str, int] = {}

    for case in cases:
        payment = session.get(Payment, case.payment_id)
        if payment is None:
            continue
        context = context_at_detection(case, builder.build(case))
        diagnosis = diagnoser.diagnose(context)
        candidates = [ActionType.RETRY_NOW] if strategy == "Baseline" else generator.generate(context, diagnosis)
        decision = engine.decide(context, diagnosis, candidates)
        verdict = policy_engine.evaluate(context, decision)
        action = decision.selected_action
        actions[action.value] = actions.get(action.value, 0) + 1
        amount_at_risk += context.amount

        if verdict.outcome is PolicyOutcome.BLOCKED:
            blocked += 1
            continue
        if verdict.outcome is PolicyOutcome.ESCALATED:
            escalated += 1
            continue
        if action in ActionType.terminal_actions():
            if action is ActionType.ESCALATE_HUMAN:
                escalated += 1
            else:
                stopped += 1
            continue

        expected_value += decision.expected_recovery_value
        would_recover, _ = simulator.predict_outcome(
            context.failure_reason,
            action,
            payment.payment_id,
            context.attempt_count + 1,
        )
        if would_recover:
            projected_recovered += context.amount

    return EvaluationMetrics(
        strategy=strategy,
        cases=len(cases),
        amount_at_risk=amount_at_risk,
        projected_recovered=projected_recovered,
        projected_recovery_rate=round(projected_recovered / amount_at_risk, 4) if amount_at_risk else 0.0,
        expected_recovery_value=expected_value,
        blocked_cases=blocked,
        escalated_cases=escalated,
        stopped_cases=stopped,
        action_distribution=actions,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate synthetic RevivePay intelligence.")
    parser.add_argument("--limit", type=int, default=60, help="maximum seeded cases to use")
    args = parser.parse_args()

    settings = get_settings()
    clock = get_clock(settings)
    with session_scope() as session:
        cases = list(
            session.execute(
                select(RecoveryCase)
                .order_by(RecoveryCase.created_at.asc(), RecoveryCase.case_id.asc())
                .limit(max(args.limit, 0))
            ).scalars().all()
        )
        if len(cases) < 4:
            print("Need at least four seeded synthetic cases. Run: python scripts/seed.py --reset")
            return 2

        split = max(2, len(cases) // 2)
        training_cases, evaluation_cases = cases[:split], cases[split:]
        training_ids = {case.case_id for case in training_cases}
        dataset = SyntheticRecoveryDatasetBuilder(session, clock, settings).build(limit=len(cases))
        training_examples = tuple(item for item in dataset if item.case_id in training_ids)
        artifact = train_logistic_model(
            training_examples,
            seed=settings.simulation_seed,
            steps=settings.local_model_training_steps,
            learning_rate=settings.local_model_learning_rate,
        )
        with tempfile.TemporaryDirectory(prefix="revivepay-eval-") as directory:
            model_path = save_artifact(artifact, Path(directory) / "local_model.json")
            local_predictor = LocalLogisticRecoveryPredictor(model_path)
            baseline = _project(
                session, clock, settings, evaluation_cases,
                strategy="Baseline", predictor=DeterministicRecoveryScorer(),
            )
            deterministic = _project(
                session, clock, settings, evaluation_cases,
                strategy="Deterministic RevivePay", predictor=DeterministicRecoveryScorer(),
            )
            ml_enhanced = _project(
                session, clock, settings, evaluation_cases,
                strategy="Local-ML RevivePay", predictor=local_predictor,
            )

    def uplift(value: int, reference: int) -> int:
        return value - reference

    report = {
        "data_source": "synthetic_simulation",
        "notice": (
            "Held-out synthetic simulation only. The command uses the same deterministic "
            "simulator and evaluation cases for all strategies; no real transaction occurs."
        ),
        "training": {
            "training_cases": len(training_cases),
            "held_out_evaluation_cases": len(evaluation_cases),
            "synthetic_training_examples": len(training_examples),
            "model_version": artifact.model_version,
        },
        "baseline": asdict(baseline),
        "deterministic_revivepay": asdict(deterministic),
        "local_ml_revivepay": asdict(ml_enhanced),
        "improvement_over_baseline": {
            "deterministic_projected_recovered": uplift(
                deterministic.projected_recovered, baseline.projected_recovered
            ),
            "local_ml_projected_recovered": uplift(
                ml_enhanced.projected_recovered, baseline.projected_recovered
            ),
            "deterministic_expected_recovery_value": uplift(
                deterministic.expected_recovery_value, baseline.expected_recovery_value
            ),
            "local_ml_expected_recovery_value": uplift(
                ml_enhanced.expected_recovery_value, baseline.expected_recovery_value
            ),
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
