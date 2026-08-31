"""Component resolution.

Each swappable component is declared as a ``Protocol`` beside its implementation
and resolved here from configuration. Phase 1 registers a different implementation
in one of these factories and changes nothing else (Requirement 27.7):

- ``RECOVERY_PREDICTOR_IMPL`` — deterministic scorer now, an ML model later
- ``DIAGNOSIS_ENGINE_IMPL`` — rule-based now, an LLM diagnoser later
- ``ACTION_EXECUTOR_IMPL`` — payment simulator now, a provider executor later

Imports are deferred into the factory bodies so that importing this module does
not pull in every component, and so that a future implementation can live behind
an optional dependency without breaking the base install.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.clock import VirtualClock, build_clock
from app.core.config import Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.integrations.action_executor import ActionExecutor
    from app.ml.predictor import RecoveryPredictor
    from app.services.diagnosis_engine import DiagnosisEngine


class UnknownImplementation(RuntimeError):
    """Configuration names an implementation that is not registered."""

    def __init__(self, kind: str, name: str, available: tuple[str, ...]) -> None:
        super().__init__(
            f"Unknown {kind} implementation '{name}'. Available: {', '.join(available)}."
        )


def get_clock(settings: Settings | None = None) -> VirtualClock:
    """Return the virtual clock."""
    if settings is None:
        return build_clock()
    return VirtualClock(
        state_path=settings.virtual_clock_state_path,
        start=settings.virtual_clock_start,
    )


def get_diagnosis_engine(settings: Settings | None = None) -> "DiagnosisEngine":
    """Resolve the diagnosis engine (Requirement 7.6)."""
    from app.services.diagnosis_engine import RuleBasedDiagnosisEngine

    resolved = settings or get_settings()
    registry = {"rule_based": RuleBasedDiagnosisEngine}

    try:
        factory = registry[resolved.diagnosis_engine_impl]
    except KeyError:
        raise UnknownImplementation(
            "diagnosis engine", resolved.diagnosis_engine_impl, tuple(registry)
        ) from None
    return factory()


def get_recovery_predictor(settings: Settings | None = None) -> "RecoveryPredictor":
    """Resolve the recovery predictor (Requirement 9.9)."""
    from app.ml.deterministic_scorer import DeterministicRecoveryScorer

    resolved = settings or get_settings()
    registry = {"deterministic": DeterministicRecoveryScorer}

    try:
        factory = registry[resolved.recovery_predictor_impl]
    except KeyError:
        raise UnknownImplementation(
            "recovery predictor", resolved.recovery_predictor_impl, tuple(registry)
        ) from None
    return factory()


def get_action_executor(
    session,
    settings: Settings | None = None,
    clock: VirtualClock | None = None,
) -> "ActionExecutor":
    """Resolve the action executor (Requirement 14.11).

    The executor is the only component permitted to change payment state, so it
    receives the session explicitly rather than reaching for a global one.
    """
    from app.integrations.payment_simulator import PaymentSimulatorExecutor

    resolved = settings or get_settings()
    registry = {"simulator": PaymentSimulatorExecutor}

    try:
        factory = registry[resolved.action_executor_impl]
    except KeyError:
        raise UnknownImplementation(
            "action executor", resolved.action_executor_impl, tuple(registry)
        ) from None
    return factory(
        session=session,
        settings=resolved,
        clock=clock or get_clock(resolved),
    )
