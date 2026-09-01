"""RecoveryPredictor adapter for the optional local logistic artifact."""

from __future__ import annotations

from math import log1p
from pathlib import Path

from app.core.enums import ActionType
from app.ml.deterministic_scorer import DeterministicRecoveryScorer
from app.ml.features import RecoveryFeatureEngineer
from app.ml.local_logistic import LocalLogisticArtifact, load_artifact, predict_probability
from app.ml.predictor import PredictionResult, ScoringFactor
from app.services.context_builder import RecoveryContext


class LocalLogisticRecoveryPredictor:
    """Use a local model artifact when valid, otherwise preserve deterministic scoring."""

    def __init__(
        self,
        artifact_path: str | Path,
        fallback: DeterministicRecoveryScorer | None = None,
    ) -> None:
        self._artifact_path = Path(artifact_path)
        self._fallback = fallback or DeterministicRecoveryScorer()
        self._features = RecoveryFeatureEngineer()
        self._artifact: LocalLogisticArtifact | None = None
        self._load_error: str | None = None
        self._load()

    @property
    def is_fallback(self) -> bool:
        return self._artifact is None

    @property
    def fallback_reason(self) -> str | None:
        return self._load_error

    @property
    def model_version(self) -> str:
        return self._artifact.model_version if self._artifact else "deterministic-fallback"

    def _load(self) -> None:
        try:
            artifact = load_artifact(self._artifact_path)
            if artifact.feature_schema_version != self._features.schema_version:
                raise ValueError("Feature schema does not match the local model artifact.")
            if artifact.feature_names != self._features.feature_names():
                raise ValueError("Feature names do not match the local model artifact.")
            self._artifact = artifact
        except (OSError, ValueError, KeyError, TypeError) as error:
            self._artifact = None
            self._load_error = f"Local model artifact unavailable or invalid ({type(error).__name__})."

    def predict(self, context: RecoveryContext, action: ActionType) -> PredictionResult:
        """Score one candidate without allowing model errors into the workflow."""

        if self._artifact is None:
            return self._fallback_result(context, action)
        vector = self._features.transform(context, action)
        try:
            probability = predict_probability(self._artifact, vector.as_dict())
        except (ValueError, ArithmeticError) as error:
            self._load_error = f"Local model prediction was invalid ({type(error).__name__})."
            return self._fallback_result(context, action)

        contributions = sorted(
            (
                (
                    abs(weight * ((vector.as_dict()[name] - mean) / max(scale, 1.0))),
                    name,
                    vector.as_dict()[name],
                    weight,
                )
                for name, mean, scale, weight in zip(
                    self._artifact.feature_names,
                    self._artifact.means,
                    self._artifact.scales,
                    self._artifact.weights,
                )
            ),
            reverse=True,
        )[:5]
        factors = tuple(
            ScoringFactor(
                name=name,
                value=round(value, 4),
                influence=round(weight, 4),
                description="Inspectable local logistic feature contribution (synthetic model).",
            )
            for _, name, value, weight in contributions
        )
        confidence = min(0.92, round(0.45 + min(log1p(self._artifact.training_samples) / 8, 0.47), 4))
        return PredictionResult(
            probability=probability,
            confidence=confidence,
            model_version=self._artifact.model_version,
            features_used=vector.names,
            explanation=factors,
        )

    def _fallback_result(self, context: RecoveryContext, action: ActionType) -> PredictionResult:
        result = self._fallback.predict(context, action)
        reason = self._load_error or "Local model artifact is unavailable."
        return PredictionResult(
            probability=result.probability,
            confidence=result.confidence,
            model_version=f"{result.model_version}:local-model-fallback",
            features_used=result.features_used,
            explanation=(
                ScoringFactor(
                    name="local_model_fallback",
                    value="unavailable",
                    influence=1.0,
                    description=reason,
                ),
                *result.explanation,
            ),
        )


__all__ = ["LocalLogisticRecoveryPredictor"]
