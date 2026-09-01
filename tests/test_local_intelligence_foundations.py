"""Safety coverage for the optional local Phase 3 foundation adapters."""

from __future__ import annotations

from dataclasses import replace

from app.core.config import Settings
from app.core.container import get_diagnosis_engine, get_recovery_predictor
from app.core.enums import ActionType, PaymentStatus
from app.ml.features import RecoveryFeatureEngineer
from app.ml.local_logistic import save_artifact, train_logistic_model
from app.ml.local_model_predictor import LocalLogisticRecoveryPredictor
from app.ml.synthetic_dataset import SyntheticRecoveryDatasetBuilder, SyntheticTrainingExample
from app.services.ai_diagnosis import AIDiagnosisEngine
from app.services.autopilot import AutopilotService
from app.services.historical_learning import HistoricalRecoveryLearning
from app.services.scenario_generator import ScenarioGenerator
from tests.test_diagnosis import make_context


def test_features_are_pre_action_and_inspectable():
    context = make_context()
    vector = RecoveryFeatureEngineer().transform(context, ActionType.RETRY_LATER)

    assert vector.names == RecoveryFeatureEngineer().feature_names()
    assert vector.as_dict()["candidate_action__RETRY_LATER"] == 1.0
    assert vector.as_dict()["candidate_action__RETRY_NOW"] == 0.0
    forbidden = {"recovered", "recovered_amount", "outcome", "case_state", "payment_status"}
    assert not forbidden & set(vector.names)
    assert vector == RecoveryFeatureEngineer().transform(
        replace(context, payment_status=PaymentStatus.SUCCEEDED), ActionType.RETRY_LATER
    )


def test_synthetic_dataset_is_reproducible_and_detection_time_safe(db, clock, settings):
    ScenarioGenerator(session=db, clock=clock, settings=settings).generate_demo_scenarios()
    db.commit()

    builder = SyntheticRecoveryDatasetBuilder(db, clock, settings)
    first = builder.build(limit=4)
    second = builder.build(limit=4)

    assert first == second
    assert first
    assert all(example.source == "synthetic_simulator_projection" for example in first)
    assert all("recovered" not in example.features.names for example in first)


def test_local_predictor_uses_deterministic_fallback_without_artifact(tmp_path):
    predictor = LocalLogisticRecoveryPredictor(tmp_path / "missing.json")
    result = predictor.predict(make_context(), ActionType.RETRY_LATER)

    assert predictor.is_fallback is True
    assert "fallback" in result.model_version
    assert result.explanation[0].name == "local_model_fallback"


def test_local_predictor_is_reproducible_with_a_json_artifact(tmp_path):
    context = make_context()
    engineer = RecoveryFeatureEngineer()
    examples = tuple(
        SyntheticTrainingExample(
            case_id=f"case_{index}",
            payment_id=f"payment_{index}",
            action=action,
            features=engineer.transform(context, action),
            recovered=index % 2 == 0,
        )
        for index, action in enumerate(
            (ActionType.RETRY_NOW, ActionType.RETRY_LATER, ActionType.SEND_PAYMENT_LINK,
             ActionType.SEND_REMINDER, ActionType.CHANGE_PAYMENT_METHOD) * 2
        )
    )
    artifact = train_logistic_model(examples, steps=30)
    path = save_artifact(artifact, tmp_path / "model.json")

    first = LocalLogisticRecoveryPredictor(path).predict(context, ActionType.RETRY_LATER)
    second = LocalLogisticRecoveryPredictor(path).predict(context, ActionType.RETRY_LATER)

    assert first == second
    assert first.model_version == "local-logistic-v1"
    assert 0.0 <= first.probability <= 1.0


def test_ai_diagnosis_rejects_malformed_provider_response_and_falls_back():
    class BrokenProvider:
        def diagnose(self, _context):
            return {"root_cause": "NOT_A_REASON"}

    engine = AIDiagnosisEngine(provider=BrokenProvider())
    diagnosis = engine.diagnose(make_context())

    assert diagnosis.failure_reason.value == "BANK_TIMEOUT"
    assert engine.last_analysis is not None
    assert engine.last_analysis.fallback_used is True


def test_ai_diagnosis_rejects_provider_failure_and_falls_back():
    class BrokenProvider:
        def diagnose(self, _context):
            raise RuntimeError("provider unavailable")

    engine = AIDiagnosisEngine(provider=BrokenProvider())
    diagnosis = engine.diagnose(make_context())

    assert diagnosis.failure_reason.value == "BANK_TIMEOUT"
    assert engine.last_analysis is not None
    assert engine.last_analysis.fallback_used is True


def test_container_keeps_deterministic_defaults_and_exposes_safe_adapters(tmp_path):
    defaults = Settings(_env_file=None, local_model_artifact_path=str(tmp_path / "missing.json"))
    assert get_recovery_predictor(defaults).model_version == "deterministic-scorer-v1"

    local = defaults.model_copy(update={"recovery_predictor_impl": "local_logistic"})
    assert get_recovery_predictor(local).is_fallback is True
    ai = defaults.model_copy(update={"diagnosis_engine_impl": "ai_local"})
    assert get_diagnosis_engine(ai).diagnose(make_context()).failure_reason.value == "BANK_TIMEOUT"


def test_historical_learning_excludes_the_current_case(db, clock, settings):
    ScenarioGenerator(session=db, clock=clock, settings=settings).generate_demo_scenarios()
    db.commit()
    AutopilotService(session=db, clock=clock, settings=settings).run_batch()

    learning = HistoricalRecoveryLearning(db)
    included = learning.insight(
        action=ActionType.CHANGE_PAYMENT_METHOD,
        failure_reason=make_context().failure_reason.EXPIRED_CARD,
        subscription_status=make_context().customer.subscription_status,
    )
    excluded = learning.insight(
        action=ActionType.CHANGE_PAYMENT_METHOD,
        failure_reason=make_context().failure_reason.EXPIRED_CARD,
        subscription_status=make_context().customer.subscription_status,
        exclude_case_id="case_demo_d",
    )

    assert included.samples >= 1
    assert excluded.samples == 0
    assert excluded.excludes_case_id == "case_demo_d"
