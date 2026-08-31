"""Route aggregation.

``GET /health`` is mounted at the application root; every other route sits under
``API_PREFIX`` (Requirement 24.5).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import analytics, health, payments, recovery, simulate

#: Mounted at the application root.
root_router = APIRouter()
root_router.include_router(health.router)

#: Mounted under the configured API prefix.
api_router = APIRouter()
api_router.include_router(payments.router)
api_router.include_router(recovery.router)
api_router.include_router(simulate.router)
api_router.include_router(analytics.router)
