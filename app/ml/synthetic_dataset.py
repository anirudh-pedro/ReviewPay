"""Reproducible synthetic labels for the local recovery model.

Examples are generated from existing synthetic recovery cases and the payment
simulator's read-only projection. They always reconstruct the context at initial
detection, so an eventual outcome from the current case cannot become a feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings
from app.core.enums import ActionType
from app.integrations.payment_simulator import PaymentSimulatorExecutor
from app.ml.features import FeatureVector, RecoveryFeatureEngineer
from app.models import RecoveryCase
from app.services.context_builder import RecoveryContext, RecoveryContextBuilder
from app.services.recovery_intelligence import context_at_detection


@dataclass(frozen=True)
class SyntheticTrainingExample:
    """One candidate-action projection and a deterministic synthetic label."""

    case_id: str
    payment_id: str
    action: ActionType
    features: FeatureVector
    recovered: bool
    source: str = "synthetic_simulator_projection"


class SyntheticRecoveryDatasetBuilder:
    """Build a bounded, deterministic candidate-action training set."""

    def __init__(self, session: Session, clock: VirtualClock, settings: Settings) -> None:
        self._session = session
        self._clock = clock
        self._settings = settings
        self._features = RecoveryFeatureEngineer()
        self._context_builder = RecoveryContextBuilder(session, clock)
        self._simulator = PaymentSimulatorExecutor(session=session, settings=settings, clock=clock)

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self._features.feature_names()

    def build(self, *, limit: int = 60) -> tuple[SyntheticTrainingExample, ...]:
        """Return stable examples from up to ``limit`` cases in detection order."""

        cases = self._session.execute(
            select(RecoveryCase)
            .order_by(RecoveryCase.created_at.asc(), RecoveryCase.case_id.asc())
            .limit(max(limit, 0))
        ).scalars().all()
        examples: list[SyntheticTrainingExample] = []
        for case in cases:
            context = context_at_detection(case, self._context_builder.build(case))
            examples.extend(self._examples_for_context(context))
        return tuple(examples)

    def _examples_for_context(
        self, context: RecoveryContext
    ) -> Iterable[SyntheticTrainingExample]:
        for action in ActionType:
            if action in ActionType.terminal_actions():
                continue
            recovered, _ = self._simulator.predict_outcome(
                context.failure_reason,
                action,
                context.payment_id,
                context.attempt_count + 1,
            )
            yield SyntheticTrainingExample(
                case_id=context.case_id,
                payment_id=context.payment_id,
                action=action,
                features=self._features.transform(context, action),
                recovered=recovered,
            )


__all__ = ["SyntheticRecoveryDatasetBuilder", "SyntheticTrainingExample"]
