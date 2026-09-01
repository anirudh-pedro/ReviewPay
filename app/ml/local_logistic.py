"""Small deterministic logistic model implemented with the Python standard library.

This is intentionally not a third-party ML dependency.  It is a compact,
inspectable baseline suited to the synthetic demonstration; model artifacts are
versioned JSON and training uses fixed batch-gradient steps.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from math import exp, log
from pathlib import Path
from typing import Iterable

from app.ml.synthetic_dataset import SyntheticTrainingExample

MODEL_VERSION = "local-logistic-v1"
ARTIFACT_VERSION = 1


@dataclass(frozen=True)
class LocalLogisticArtifact:
    """Portable model state, safe to persist as JSON."""

    artifact_version: int
    model_version: str
    feature_schema_version: str
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[float, ...]
    intercept: float
    training_samples: int
    positive_samples: int
    seed: int
    steps: int
    learning_rate: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "LocalLogisticArtifact":
        return cls(
            artifact_version=int(value["artifact_version"]),
            model_version=str(value["model_version"]),
            feature_schema_version=str(value["feature_schema_version"]),
            feature_names=tuple(str(item) for item in value["feature_names"]),
            means=tuple(float(item) for item in value["means"]),
            scales=tuple(float(item) for item in value["scales"]),
            weights=tuple(float(item) for item in value["weights"]),
            intercept=float(value["intercept"]),
            training_samples=int(value["training_samples"]),
            positive_samples=int(value["positive_samples"]),
            seed=int(value["seed"]),
            steps=int(value["steps"]),
            learning_rate=float(value["learning_rate"]),
        )


def _sigmoid(value: float) -> float:
    bounded = max(min(value, 30.0), -30.0)
    return 1.0 / (1.0 + exp(-bounded))


def train_logistic_model(
    examples: Iterable[SyntheticTrainingExample],
    *,
    seed: int = 20260101,
    steps: int = 240,
    learning_rate: float = 0.12,
) -> LocalLogisticArtifact:
    """Fit a deterministic, L2-regularized logistic classifier."""

    rows = tuple(examples)
    if not rows:
        raise ValueError("At least one synthetic training example is required.")
    feature_names = rows[0].features.names
    if not feature_names or any(row.features.names != feature_names for row in rows):
        raise ValueError("Training examples must share one stable feature schema.")

    matrix = [[row.features.as_dict()[name] for name in feature_names] for row in rows]
    labels = [1.0 if row.recovered else 0.0 for row in rows]
    count = len(rows)
    means = tuple(sum(row[index] for row in matrix) / count for index in range(len(feature_names)))
    scales = tuple(
        max(
            (sum((row[index] - means[index]) ** 2 for row in matrix) / count) ** 0.5,
            1.0,
        )
        for index in range(len(feature_names))
    )
    normalized = [
        [(row[index] - means[index]) / scales[index] for index in range(len(feature_names))]
        for row in matrix
    ]
    weights = [0.0] * len(feature_names)
    intercept = log((sum(labels) + 0.5) / (count - sum(labels) + 0.5))
    regularization = 0.01

    for _ in range(max(steps, 1)):
        errors = [
            _sigmoid(intercept + sum(weight * value for weight, value in zip(weights, row)))
            - label
            for row, label in zip(normalized, labels)
        ]
        intercept -= learning_rate * sum(errors) / count
        for index in range(len(weights)):
            gradient = sum(error * row[index] for error, row in zip(errors, normalized)) / count
            weights[index] -= learning_rate * (gradient + regularization * weights[index])

    return LocalLogisticArtifact(
        artifact_version=ARTIFACT_VERSION,
        model_version=MODEL_VERSION,
        feature_schema_version="recovery-pre-action-v1",
        feature_names=feature_names,
        means=means,
        scales=scales,
        weights=tuple(weights),
        intercept=intercept,
        training_samples=count,
        positive_samples=int(sum(labels)),
        seed=seed,
        steps=steps,
        learning_rate=learning_rate,
    )


def predict_probability(artifact: LocalLogisticArtifact, values: dict[str, float]) -> float:
    """Score an inspectable feature mapping with a validated artifact."""

    if artifact.artifact_version != ARTIFACT_VERSION:
        raise ValueError("Unsupported local model artifact version.")
    if len(artifact.feature_names) != len(artifact.weights):
        raise ValueError("Local model artifact weights do not match its feature schema.")
    score = artifact.intercept
    for name, mean, scale, weight in zip(
        artifact.feature_names, artifact.means, artifact.scales, artifact.weights
    ):
        if name not in values:
            raise ValueError(f"Local model artifact expects missing feature '{name}'.")
        score += weight * ((values[name] - mean) / max(scale, 1.0))
    return round(_sigmoid(score), 4)


def save_artifact(artifact: LocalLogisticArtifact, path: str | Path) -> Path:
    """Persist a reproducible JSON model artifact locally."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def load_artifact(path: str | Path) -> LocalLogisticArtifact:
    """Load and structurally validate a JSON artifact."""

    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Local model artifact must contain a JSON object.")
    return LocalLogisticArtifact.from_dict(value)


__all__ = [
    "ARTIFACT_VERSION",
    "MODEL_VERSION",
    "LocalLogisticArtifact",
    "load_artifact",
    "predict_probability",
    "save_artifact",
    "train_logistic_model",
]
