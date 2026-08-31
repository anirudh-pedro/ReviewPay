"""Analytics response schemas (Requirement 24.4, 20.5).

Every payload carries the synthetic-data marker: these numbers come from a
deterministic simulation, not from real payment traffic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import Money, SyntheticNotice


class RevenueAnalyticsResponse(SyntheticNotice):
    """Revenue at risk versus revenue actually recovered (Requirement 20.1)."""

    revenue_at_risk: Money
    revenue_recovered: Money
    recovery_rate: float = Field(
        description="Recovered revenue divided by revenue at risk. Zero when nothing is at risk."
    )
    average_recovery_value: Money = Field(
        description="Mean recovered amount across verified successful recoveries."
    )
    cases_total: int
    cases_recovered: int
    payments_at_risk: int


class ActionCounts(BaseModel):
    """Action dispositions across all cases (Requirement 20.2)."""

    selected: int
    successful: int
    failed: int
    stopped: int
    escalated: int


class RecoveryAnalyticsResponse(SyntheticNotice):
    """Recovery performance metrics (Requirement 20.2)."""

    average_recovery_probability: float
    actions: ActionCounts
    verified_outcomes: int
    cases_by_state: dict[str, int] = Field(default_factory=dict)
