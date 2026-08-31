"""Recovery prediction interface.

``RecoveryPredictor`` is the seam where Phase 1 replaces deterministic scoring with
a trained model. Everything downstream — valuation, ranking, policy, execution —
depends on ``PredictionResult`` and not on how the number was produced
(Requirement 9.1, 9.9).

The result deliberately carries more than a probability. ``confidence``,
``model_version``, ``features_used``, and ``explanation`` are what let the system
answer "why did it choose this?", and they are populated in Phase 0 so that the
contract does not change when the implementation does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.core.enums import ActionType
from app.services.context_builder import RecoveryContext


@dataclass(frozen=True)
class ScoringFactor:
    """One contribution to a predicted probability.

    ``influence`` is the multiplier the factor applied (1.0 means no effect), except
    for the anchoring base rate, where it is the rate itself.
    """

    name: str
    value: Any
    influence: float
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "influence": round(self.influence, 4),
            "description": self.description,
        }


@dataclass(frozen=True)
class PredictionResult:
    """A recovery probability with the reasoning that produced it."""

    probability: float
    confidence: float
    model_version: str
    features_used: tuple[str, ...]
    explanation: tuple[ScoringFactor, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"probability {self.probability} outside [0.0, 1.0]")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence {self.confidence} outside [0.0, 1.0]")

    @property
    def top_factor(self) -> ScoringFactor | None:
        """The single most influential factor, for one-line demo output."""
        return self.explanation[0] if self.explanation else None

    def explanation_text(self) -> str:
        """Human-readable summary of the reasoning."""
        return "; ".join(
            f"{factor.name}={factor.value} (x{factor.influence:.3f})"
            for factor in self.explanation
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "probability": self.probability,
            "confidence": self.confidence,
            "model_version": self.model_version,
            "features_used": list(self.features_used),
            "explanation": [factor.to_dict() for factor in self.explanation],
        }


@runtime_checkable
class RecoveryPredictor(Protocol):
    """Estimates the probability that an action recovers a payment."""

    def predict(self, context: RecoveryContext, action: ActionType) -> PredictionResult: ...


__all__ = ["PredictionResult", "RecoveryPredictor", "ScoringFactor"]
