"""Demo control endpoints.

Resets the synthetic dataset and the virtual clock so a demonstration can be run
repeatedly and land on identical numbers every time.

**This endpoint is destructive and is gated on the environment profile.** It drops
and recreates every table, so it refuses to run unless the resolved profile is
``local``, ``demo``, or ``test``. That guard is deliberate: a reset endpoint
reachable in staging or production would be a way to erase an audit trail, and the
audit trail is the thing this system asks to be trusted on.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.auth import DemoResetPrincipalDep
from app.api.deps import ClockDep, SessionDep, SettingsDep
from app.api.routes.command_center import scenario_reads
from app.core.config import ENVIRONMENT_PROFILE_ALIASES, RESETTABLE_PROFILES
from app.core.errors import RevivePayError
from app.core.logging import get_logger
from app.schemas.product import DemoResetRequest, DemoResetResponse
from app.services.scenario_generator import ScenarioGenerator

logger = get_logger("demo")

router = APIRouter(prefix="/demo", tags=["demo"])

#: ``ENVIRONMENT`` labels that resolve to a profile permitting destructive reset.
RESETTABLE_ENVIRONMENTS = frozenset(
    label for label, profile in ENVIRONMENT_PROFILE_ALIASES.items() if profile in RESETTABLE_PROFILES
)


class DemoResetForbidden(RevivePayError):
    """Reset was attempted outside an explicitly resettable environment profile."""

    code = "DEMO_RESET_FORBIDDEN"
    http_status = 403

    def __init__(self, environment: str) -> None:
        super().__init__(
            f"Demo reset is not permitted while ENVIRONMENT is '{environment}'. "
            f"Permitted profiles: {', '.join(sorted(RESETTABLE_PROFILES))}."
        )
        self.environment = environment


@router.post(
    "/reset",
    response_model=DemoResetResponse,
    summary="Reset synthetic data, the virtual clock, and the demo scenarios",
)
def reset_demo(
    request: DemoResetRequest,
    session: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
    _: DemoResetPrincipalDep,
) -> DemoResetResponse:
    """Restore the deterministic starting state.

    Reseeding with the same simulation seed reproduces byte-identical rows, so the
    demo tells the same story on the tenth run as on the first.
    """
    if not settings.profile_policy.allows_destructive_reset:
        raise DemoResetForbidden(settings.environment)

    from app.db.base import Base

    # Operate on the engine behind *this request's* session rather than the
    # module-level one. They are normally the same, but binding to the session keeps
    # reset correct whenever they diverge — a test database, or a session opened
    # against a different DATABASE_URL. Using the global engine here silently wiped
    # one database while the request kept reading another.
    bind = session.get_bind()

    # Log the profile and dialect, not the connection string.
    logger.warning(
        "demo reset requested | profile=%s | rebuilding schema on dialect=%s",
        settings.environment_profile,
        getattr(getattr(bind, "dialect", None), "name", "unknown"),
    )

    # Release the session's view before the schema is rebuilt underneath it.
    session.rollback()
    session.expunge_all()

    Base.metadata.drop_all(bind=bind)
    Base.metadata.create_all(bind=bind)

    clock.reset()

    generator = ScenarioGenerator(session=session, clock=clock, settings=settings)
    summary = generator.generate(background_customers=request.background_customers)
    session.commit()

    logger.info(
        "demo reset complete | customers=%s payments=%s cases=%s",
        summary.customers,
        summary.payments,
        summary.cases,
    )

    return DemoResetResponse(
        customers=summary.customers,
        payments=summary.payments,
        cases=summary.cases,
        scenarios=scenario_reads(session),
        virtual_clock_time=clock.now(),
        message=(
            f"Synthetic dataset reseeded from simulation seed {settings.simulation_seed}. "
            f"Simulation time reset to {clock.now().isoformat()}. "
            "No real payment data was involved."
        ),
    )
