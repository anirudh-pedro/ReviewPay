"""Route aggregation.

``GET /health`` is mounted at the application root; every other route sits under
``API_PREFIX`` (Requirement 24.5).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    analytics,
    command_center,
    demo,
    gateway,
    health,
    intelligence,
    jobs,
    payments,
    recovery,
    simulate,
)

#: Mounted at the application root.
root_router = APIRouter()
root_router.include_router(health.router)

#: Mounted under the configured API prefix.
#:
#: ``command_center`` shares the ``/recovery`` prefix with ``recovery`` and is
#: included first so its static paths (``/overview``, ``/scenarios``, ``/baseline``)
#: are matched before ``recovery``'s ``/cases/{case_id}`` style parameters.
api_router = APIRouter()
api_router.include_router(command_center.router)
api_router.include_router(intelligence.router)
api_router.include_router(jobs.router)
api_router.include_router(payments.router)
api_router.include_router(gateway.router)
api_router.include_router(recovery.router)
api_router.include_router(simulate.router)
api_router.include_router(analytics.router)
api_router.include_router(demo.router)
