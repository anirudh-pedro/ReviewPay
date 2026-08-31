"""Analytics endpoints (Requirement 24.4).

Both payloads carry the synthetic-data marker, so no figure served here can be
mistaken for a real payment result (Requirement 20.5, 27.1).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.schemas.analytics import (
    ActionCounts,
    RecoveryAnalyticsResponse,
    RevenueAnalyticsResponse,
)
from app.schemas.common import Money
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/revenue",
    response_model=RevenueAnalyticsResponse,
    summary="Revenue at risk versus revenue actually recovered",
)
def revenue_analytics(session: SessionDep) -> RevenueAnalyticsResponse:
    metrics = AnalyticsService(session).revenue()
    return RevenueAnalyticsResponse(
        revenue_at_risk=Money.of(metrics.revenue_at_risk),
        revenue_recovered=Money.of(metrics.revenue_recovered),
        recovery_rate=metrics.recovery_rate,
        average_recovery_value=Money.of(metrics.average_recovery_value),
        cases_total=metrics.cases_total,
        cases_recovered=metrics.cases_recovered,
        payments_at_risk=metrics.payments_at_risk,
    )


@router.get(
    "/recovery",
    response_model=RecoveryAnalyticsResponse,
    summary="Recovery performance and action dispositions",
)
def recovery_analytics(session: SessionDep) -> RecoveryAnalyticsResponse:
    metrics = AnalyticsService(session).recovery()
    return RecoveryAnalyticsResponse(
        average_recovery_probability=metrics.average_recovery_probability,
        actions=ActionCounts(
            selected=metrics.actions.selected,
            successful=metrics.actions.successful,
            failed=metrics.actions.failed,
            stopped=metrics.actions.stopped,
            escalated=metrics.actions.escalated,
        ),
        verified_outcomes=metrics.verified_outcomes,
        cases_by_state=metrics.cases_by_state,
    )
