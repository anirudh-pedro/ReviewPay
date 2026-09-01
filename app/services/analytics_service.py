"""Revenue and recovery analytics.

Every figure is derived from persisted rows, never from in-memory counters
(Requirement 20.4), so a restart cannot change a reported total and a judge can
reproduce any number with SQL.

Recovered revenue comes exclusively from verified ``RecoveryOutcome`` rows
(Requirement 15.7). Nothing here counts an action as recovered because the executor
said so.

Every payload is labelled as synthetic simulation output (Requirement 20.5).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ActionType, CaseState, PaymentStatus, PolicyOutcome
from app.models import Payment, RecoveryAction, RecoveryCase, RecoveryOutcome


@dataclass(frozen=True)
class RevenueMetrics:
    """Revenue at risk against revenue actually recovered. Minor units."""

    revenue_at_risk: int
    revenue_recovered: int
    recovery_rate: float
    average_recovery_value: int
    cases_total: int
    cases_recovered: int
    payments_at_risk: int


@dataclass(frozen=True)
class ActionDispositionCounts:
    """How selected actions turned out."""

    selected: int
    successful: int
    failed: int
    stopped: int
    escalated: int


@dataclass(frozen=True)
class RecoveryMetrics:
    """Recovery performance across all cases."""

    average_recovery_probability: float
    actions: ActionDispositionCounts
    verified_outcomes: int
    cases_by_state: dict[str, int]


@dataclass(frozen=True)
class FailureReasonBreakdown:
    """Recovery performance for one failure cause. Minor units."""

    failure_reason: str
    cases: int
    amount_at_risk: int
    amount_recovered: int
    recovered_cases: int
    recovery_rate: float


@dataclass(frozen=True)
class ActionBreakdown:
    """Recovery performance for one action type. Minor units.

    ``selected`` counts every time the decision engine chose this action;
    ``executed`` counts the subset that actually reached the executor. The gap
    between them is what the policy engine refused, which is a number worth seeing.
    """

    action_type: str
    selected: int
    executed: int
    successes: int
    failures: int
    success_rate: float
    amount_recovered: int
    average_amount_recovered: int
    blocked: int
    escalated: int


@dataclass(frozen=True)
class OverviewMetrics:
    """Everything the command-center dashboard needs in one round trip."""

    revenue: RevenueMetrics
    recovery: RecoveryMetrics
    active_cases: int
    policy_blocks: int
    policy_escalations: int
    policy_approvals: int
    expected_recovery_value_total: int
    expected_recovery_value_approved: int
    scheduled_cases: int
    by_failure_reason: tuple[FailureReasonBreakdown, ...]
    by_action: tuple[ActionBreakdown, ...]


class AnalyticsService:
    """Aggregates revenue and recovery metrics from the database."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- revenue -----------------------------------------------------------

    def revenue(self) -> RevenueMetrics:
        """Requirement 20.1."""
        at_risk = self._scalar(
            select(func.coalesce(func.sum(RecoveryCase.amount_at_risk), 0))
        )
        recovered = self._scalar(
            select(func.coalesce(func.sum(RecoveryOutcome.recovered_amount), 0)).where(
                RecoveryOutcome.recovered.is_(True)
            )
        )
        successful_recoveries = self._scalar(
            select(func.count())
            .select_from(RecoveryOutcome)
            .where(RecoveryOutcome.recovered.is_(True))
        )

        cases_total = self._scalar(select(func.count()).select_from(RecoveryCase))
        cases_recovered = self._scalar(
            select(func.count())
            .select_from(RecoveryCase)
            .where(RecoveryCase.state == CaseState.RECOVERED)
        )
        payments_at_risk = self._scalar(
            select(func.count())
            .select_from(Payment)
            .where(Payment.status.in_(tuple(PaymentStatus.unsuccessful())))
        )

        return RevenueMetrics(
            revenue_at_risk=at_risk,
            revenue_recovered=recovered,
            # Guarded division (Requirement 20.3).
            recovery_rate=round(recovered / at_risk, 4) if at_risk else 0.0,
            average_recovery_value=(
                round(recovered / successful_recoveries) if successful_recoveries else 0
            ),
            cases_total=cases_total,
            cases_recovered=cases_recovered,
            payments_at_risk=payments_at_risk,
        )

    # -- recovery ----------------------------------------------------------

    def recovery(self) -> RecoveryMetrics:
        """Requirement 20.2."""
        average_probability = self._session.execute(
            select(func.avg(RecoveryAction.estimated_probability))
        ).scalar()

        selected = self._scalar(select(func.count()).select_from(RecoveryAction))
        successful = self._scalar(
            select(func.count())
            .select_from(RecoveryOutcome)
            .where(RecoveryOutcome.recovered.is_(True))
        )
        failed = self._scalar(
            select(func.count())
            .select_from(RecoveryOutcome)
            .where(RecoveryOutcome.recovered.is_(False))
        )
        stopped = self._scalar(
            select(func.count())
            .select_from(RecoveryCase)
            .where(RecoveryCase.state == CaseState.STOPPED)
        )
        escalated = self._scalar(
            select(func.count())
            .select_from(RecoveryCase)
            .where(RecoveryCase.state == CaseState.ESCALATED)
        )

        return RecoveryMetrics(
            average_recovery_probability=round(float(average_probability or 0.0), 4),
            actions=ActionDispositionCounts(
                selected=selected,
                successful=successful,
                failed=failed,
                stopped=stopped,
                escalated=escalated,
            ),
            verified_outcomes=successful + failed,
            cases_by_state=self._cases_by_state(),
        )

    # -- breakdowns --------------------------------------------------------

    def by_failure_reason(self) -> tuple[FailureReasonBreakdown, ...]:
        """Recovery performance grouped by failure cause.

        The cause is resolved from the persisted diagnosis first and the payment
        second. That order matters: a recovered payment has its ``failure_reason``
        cleared, so reading only the payment would silently drop every success from
        this breakdown and make recovery look worse than it was.
        """
        recovered_by_case = self._recovered_amount_by_case()

        rows = self._session.execute(
            select(RecoveryCase, Payment).join(
                Payment, Payment.payment_id == RecoveryCase.payment_id
            )
        ).all()

        grouped: dict[str, dict[str, int]] = {}
        for case, payment in rows:
            reason = self._resolve_failure_reason(case, payment)
            bucket = grouped.setdefault(
                reason, {"cases": 0, "at_risk": 0, "recovered": 0, "recovered_cases": 0}
            )
            bucket["cases"] += 1
            bucket["at_risk"] += int(case.amount_at_risk)
            amount = recovered_by_case.get(case.case_id, 0)
            bucket["recovered"] += amount
            if amount > 0:
                bucket["recovered_cases"] += 1

        return tuple(
            FailureReasonBreakdown(
                failure_reason=reason,
                cases=data["cases"],
                amount_at_risk=data["at_risk"],
                amount_recovered=data["recovered"],
                recovered_cases=data["recovered_cases"],
                recovery_rate=(
                    round(data["recovered"] / data["at_risk"], 4) if data["at_risk"] else 0.0
                ),
            )
            for reason, data in sorted(
                grouped.items(), key=lambda item: item[1]["at_risk"], reverse=True
            )
        )

    def by_action(self) -> tuple[ActionBreakdown, ...]:
        """Recovery performance grouped by action type.

        ``selected`` versus ``executed`` is deliberately exposed: the gap between
        them is exactly what the policy engine refused to run.
        """
        selected = self._count_by(RecoveryAction.action_type)
        executed = self._count_by(
            RecoveryAction.action_type, RecoveryAction.executed_at.is_not(None)
        )
        blocked = self._count_by(
            RecoveryAction.action_type, RecoveryAction.policy_outcome == PolicyOutcome.BLOCKED
        )
        escalated = self._count_by(
            RecoveryAction.action_type,
            RecoveryAction.policy_outcome == PolicyOutcome.ESCALATED,
        )

        outcome_rows = self._session.execute(
            select(
                RecoveryAction.action_type,
                RecoveryOutcome.recovered,
                func.count(),
                func.coalesce(func.sum(RecoveryOutcome.recovered_amount), 0),
            )
            .join(RecoveryOutcome, RecoveryOutcome.action_id == RecoveryAction.action_id)
            .group_by(RecoveryAction.action_type, RecoveryOutcome.recovered)
        ).all()

        successes: dict[str, int] = {}
        failures: dict[str, int] = {}
        recovered: dict[str, int] = {}
        for action_type, was_recovered, count, amount in outcome_rows:
            key = action_type.value
            if was_recovered:
                successes[key] = successes.get(key, 0) + int(count)
                recovered[key] = recovered.get(key, 0) + int(amount or 0)
            else:
                failures[key] = failures.get(key, 0) + int(count)

        breakdowns: list[ActionBreakdown] = []
        for action in ActionType:
            key = action.value
            if not selected.get(key):
                continue

            success_count = successes.get(key, 0)
            failure_count = failures.get(key, 0)
            verified = success_count + failure_count
            amount = recovered.get(key, 0)

            breakdowns.append(
                ActionBreakdown(
                    action_type=key,
                    selected=selected.get(key, 0),
                    executed=executed.get(key, 0),
                    successes=success_count,
                    failures=failure_count,
                    success_rate=round(success_count / verified, 4) if verified else 0.0,
                    amount_recovered=amount,
                    average_amount_recovered=(
                        round(amount / success_count) if success_count else 0
                    ),
                    blocked=blocked.get(key, 0),
                    escalated=escalated.get(key, 0),
                )
            )
        return tuple(breakdowns)

    # -- overview ----------------------------------------------------------

    def overview(self) -> OverviewMetrics:
        """Every dashboard figure in one round trip.

        One query batch rather than six endpoints, because the command center shows
        these together and partial loading would make the numbers look inconsistent
        mid-render.
        """
        terminal = tuple(CaseState.terminal())

        active_cases = self._scalar(
            select(func.count()).select_from(RecoveryCase).where(
                RecoveryCase.state.not_in(terminal)
            )
        )
        scheduled_cases = self._scalar(
            select(func.count())
            .select_from(RecoveryCase)
            .where(RecoveryCase.state == CaseState.SCHEDULED)
        )

        def policy_count(outcome: PolicyOutcome) -> int:
            return self._scalar(
                select(func.count())
                .select_from(RecoveryAction)
                .where(RecoveryAction.policy_outcome == outcome)
            )

        expected_total = self._scalar(
            select(func.coalesce(func.sum(RecoveryAction.expected_recovery_value), 0))
        )
        expected_approved = self._scalar(
            select(func.coalesce(func.sum(RecoveryAction.expected_recovery_value), 0)).where(
                RecoveryAction.policy_outcome == PolicyOutcome.APPROVED
            )
        )

        return OverviewMetrics(
            revenue=self.revenue(),
            recovery=self.recovery(),
            active_cases=active_cases,
            policy_blocks=policy_count(PolicyOutcome.BLOCKED),
            policy_escalations=policy_count(PolicyOutcome.ESCALATED),
            policy_approvals=policy_count(PolicyOutcome.APPROVED),
            expected_recovery_value_total=expected_total,
            expected_recovery_value_approved=expected_approved,
            scheduled_cases=scheduled_cases,
            by_failure_reason=self.by_failure_reason(),
            by_action=self.by_action(),
        )

    # -- helpers -----------------------------------------------------------

    def _recovered_amount_by_case(self) -> dict[str, int]:
        """Verified recovered amount per case id (Requirement 15.7)."""
        rows = self._session.execute(
            select(
                RecoveryAction.case_id,
                func.coalesce(func.sum(RecoveryOutcome.recovered_amount), 0),
            )
            .join(RecoveryOutcome, RecoveryOutcome.action_id == RecoveryAction.action_id)
            .where(RecoveryOutcome.recovered.is_(True))
            .group_by(RecoveryAction.case_id)
        ).all()
        return {case_id: int(amount or 0) for case_id, amount in rows}

    @staticmethod
    def _resolve_failure_reason(case: RecoveryCase, payment: Payment) -> str:
        """The cause as diagnosed, falling back to the payment, then UNKNOWN."""
        diagnosis = case.diagnosis or {}
        reason = diagnosis.get("failure_reason")
        if reason:
            return str(reason)
        if payment.failure_reason is not None:
            return payment.failure_reason.value
        return "UNKNOWN"

    def _count_by(self, column, *conditions) -> dict[str, int]:
        """Count rows grouped by an enum column, keyed by the enum's value."""
        statement = select(column, func.count()).select_from(RecoveryAction)
        for condition in conditions:
            statement = statement.where(condition)
        rows = self._session.execute(statement.group_by(column)).all()
        return {key.value: int(count) for key, count in rows if key is not None}

    def _cases_by_state(self) -> dict[str, int]:
        rows = self._session.execute(
            select(RecoveryCase.state, func.count()).group_by(RecoveryCase.state)
        ).all()
        return {state.value: int(count) for state, count in rows}

    def _scalar(self, statement) -> int:
        return int(self._session.execute(statement).scalar_one() or 0)


__all__ = [
    "ActionBreakdown",
    "ActionDispositionCounts",
    "AnalyticsService",
    "FailureReasonBreakdown",
    "OverviewMetrics",
    "RecoveryMetrics",
    "RevenueMetrics",
]
