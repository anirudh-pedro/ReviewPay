"""Analytics tests (Requirement 20.1-20.5, 15.7)."""

from __future__ import annotations

import pytest

from app.core.enums import (
    ActionStatus,
    ActionType,
    CaseState,
    FailureReason,
    PaymentStatus,
    RiskLevel,
)
from app.models import RecoveryAction, RecoveryCase, RecoveryOutcome
from app.schemas.common import SYNTHETIC_DATA_SOURCE
from app.services.analytics_service import AnalyticsService


@pytest.fixture
def analytics(db) -> AnalyticsService:
    return AnalyticsService(db)


@pytest.fixture
def make_case(db, clock, payment_factory):
    """Build a case with an optional action and verified outcome."""
    counter = {"n": 0}

    def _make(
        *,
        amount: int = 1_000_000,
        state: CaseState = CaseState.DETECTED,
        action_type: ActionType | None = None,
        probability: float = 0.776,
        recovered: bool | None = None,
    ) -> RecoveryCase:
        counter["n"] += 1
        now = clock.now()
        payment = payment_factory(
            amount=amount,
            status=PaymentStatus.SUCCEEDED if recovered else PaymentStatus.FAILED,
            failure_reason=None if recovered else FailureReason.BANK_TIMEOUT,
        )
        case = RecoveryCase(
            case_id=f"case_an_{counter['n']:04d}",
            payment_id=payment.payment_id,
            state=state,
            amount_at_risk=amount,
            created_at=now,
            updated_at=now,
        )
        db.add(case)
        db.flush()

        if action_type is not None:
            action = RecoveryAction(
                action_id=f"act_an_{counter['n']:04d}",
                case_id=case.case_id,
                payment_id=payment.payment_id,
                action_type=action_type,
                estimated_probability=probability,
                confidence=1.0,
                model_version="deterministic-scorer-v1",
                expected_recovery_value=764_000,
                erv_breakdown={},
                risk_level=RiskLevel.LOW,
                decision_explanation={},
                status=ActionStatus.EXECUTED,
                created_at=now,
                executed_at=now,
            )
            db.add(action)
            db.flush()

            if recovered is not None:
                db.add(
                    RecoveryOutcome(
                        outcome_id=f"out_an_{counter['n']:04d}",
                        action_id=action.action_id,
                        previous_payment_status=PaymentStatus.FAILED,
                        new_payment_status=(
                            PaymentStatus.SUCCEEDED if recovered else PaymentStatus.FAILED
                        ),
                        recovered=recovered,
                        recovered_amount=amount if recovered else 0,
                        verification_timestamp=now,
                    )
                )
        db.commit()
        return case

    return _make


# ---------------------------------------------------------------------------
# Revenue (Requirement 20.1)
# ---------------------------------------------------------------------------


def test_revenue_at_risk_sums_case_amounts(analytics, make_case):
    make_case(amount=1_000_000)
    make_case(amount=250_000)

    metrics = analytics.revenue()
    assert metrics.revenue_at_risk == 1_250_000
    assert metrics.cases_total == 2


def test_revenue_recovered_counts_verified_outcomes_only(analytics, make_case):
    """Requirement 15.7."""
    make_case(amount=1_000_000, action_type=ActionType.RETRY_LATER, recovered=True,
              state=CaseState.RECOVERED)
    make_case(amount=500_000, action_type=ActionType.RETRY_LATER, recovered=False)
    # An action with no verified outcome contributes nothing.
    make_case(amount=300_000, action_type=ActionType.SEND_REMINDER, recovered=None)

    metrics = analytics.revenue()
    assert metrics.revenue_recovered == 1_000_000
    assert metrics.cases_recovered == 1


def test_recovery_rate_is_recovered_over_at_risk(analytics, make_case):
    make_case(amount=1_000_000, action_type=ActionType.RETRY_LATER, recovered=True,
              state=CaseState.RECOVERED)
    make_case(amount=1_000_000, action_type=ActionType.RETRY_LATER, recovered=False)

    assert analytics.revenue().recovery_rate == pytest.approx(0.5)


def test_recovery_rate_is_zero_when_nothing_is_at_risk(analytics):
    """Requirement 20.3: guarded division."""
    metrics = analytics.revenue()
    assert metrics.revenue_at_risk == 0
    assert metrics.recovery_rate == 0.0
    assert metrics.average_recovery_value == 0


def test_average_recovery_value_averages_successful_recoveries(analytics, make_case):
    make_case(amount=1_000_000, action_type=ActionType.RETRY_LATER, recovered=True,
              state=CaseState.RECOVERED)
    make_case(amount=500_000, action_type=ActionType.RETRY_LATER, recovered=True,
              state=CaseState.RECOVERED)
    make_case(amount=900_000, action_type=ActionType.RETRY_LATER, recovered=False)

    assert analytics.revenue().average_recovery_value == 750_000


def test_payments_at_risk_counts_unsuccessful_payments(analytics, make_case):
    make_case(amount=100_000)
    make_case(amount=100_000, action_type=ActionType.RETRY_LATER, recovered=True,
              state=CaseState.RECOVERED)

    assert analytics.revenue().payments_at_risk == 1


def test_monetary_metrics_are_integers(analytics, make_case):
    """Requirement 20.1: minor units."""
    make_case(amount=1_000_000, action_type=ActionType.RETRY_LATER, recovered=True,
              state=CaseState.RECOVERED)
    metrics = analytics.revenue()

    assert isinstance(metrics.revenue_at_risk, int)
    assert isinstance(metrics.revenue_recovered, int)
    assert isinstance(metrics.average_recovery_value, int)


# ---------------------------------------------------------------------------
# Recovery (Requirement 20.2)
# ---------------------------------------------------------------------------


def test_action_dispositions_are_counted(analytics, make_case):
    make_case(action_type=ActionType.RETRY_LATER, recovered=True, state=CaseState.RECOVERED)
    make_case(action_type=ActionType.RETRY_LATER, recovered=False, state=CaseState.STOPPED)
    make_case(action_type=ActionType.ESCALATE_HUMAN, state=CaseState.ESCALATED)

    metrics = analytics.recovery()
    assert metrics.actions.selected == 3
    assert metrics.actions.successful == 1
    assert metrics.actions.failed == 1
    assert metrics.actions.stopped == 1
    assert metrics.actions.escalated == 1
    assert metrics.verified_outcomes == 2


def test_average_recovery_probability(analytics, make_case):
    make_case(action_type=ActionType.RETRY_LATER, probability=0.8)
    make_case(action_type=ActionType.RETRY_NOW, probability=0.4)

    assert analytics.recovery().average_recovery_probability == pytest.approx(0.6)


def test_average_probability_is_zero_with_no_actions(analytics):
    assert analytics.recovery().average_recovery_probability == 0.0


def test_cases_by_state(analytics, make_case):
    make_case(state=CaseState.RECOVERED, action_type=ActionType.RETRY_LATER, recovered=True)
    make_case(state=CaseState.STOPPED)
    make_case(state=CaseState.STOPPED)

    assert analytics.recovery().cases_by_state == {"RECOVERED": 1, "STOPPED": 2}


# ---------------------------------------------------------------------------
# Derivation from persisted rows (Requirement 20.4)
# ---------------------------------------------------------------------------


def test_metrics_survive_a_new_service_instance(db, make_case):
    """Requirement 20.4: nothing is held in memory."""
    make_case(amount=1_000_000, action_type=ActionType.RETRY_LATER, recovered=True,
              state=CaseState.RECOVERED)

    first = AnalyticsService(db).revenue()
    second = AnalyticsService(db).revenue()
    assert first == second


# ---------------------------------------------------------------------------
# Endpoints (Requirement 24.4, 20.5)
# ---------------------------------------------------------------------------


def test_revenue_endpoint_shape_and_provenance(api_client, api_prefix):
    """Requirement 20.5, 27.1."""
    response = api_client.get(f"{api_prefix}/analytics/revenue")
    assert response.status_code == 200

    body = response.json()
    assert body["revenue_at_risk"] == {"amount": 0, "currency": "INR"}
    assert body["revenue_recovered"] == {"amount": 0, "currency": "INR"}
    assert body["recovery_rate"] == 0.0
    assert body["data_source"] == SYNTHETIC_DATA_SOURCE
    assert "no real money" in body["notice"].lower()


def test_recovery_endpoint_shape_and_provenance(api_client, api_prefix):
    response = api_client.get(f"{api_prefix}/analytics/recovery")
    assert response.status_code == 200

    body = response.json()
    assert set(body["actions"]) == {
        "selected",
        "successful",
        "failed",
        "stopped",
        "escalated",
    }
    assert body["data_source"] == SYNTHETIC_DATA_SOURCE


def test_endpoints_reflect_recorded_activity(api_client, api_prefix, make_case):
    make_case(amount=1_000_000, action_type=ActionType.RETRY_LATER, recovered=True,
              state=CaseState.RECOVERED)

    revenue = api_client.get(f"{api_prefix}/analytics/revenue").json()
    assert revenue["revenue_at_risk"]["amount"] == 1_000_000
    assert revenue["revenue_recovered"]["amount"] == 1_000_000
    assert revenue["recovery_rate"] == 1.0

    recovery = api_client.get(f"{api_prefix}/analytics/recovery").json()
    assert recovery["actions"]["selected"] == 1
    assert recovery["actions"]["successful"] == 1


# ---------------------------------------------------------------------------
# Clock endpoints (Requirement 18.6, 24.4)
# ---------------------------------------------------------------------------


def test_advance_clock_endpoint(api_client, api_prefix, clock):
    before = clock.now()
    response = api_client.post(f"{api_prefix}/simulate/advance-clock", json={"minutes": 15})
    assert response.status_code == 200

    body = response.json()
    assert body["advanced_by_minutes"] == 15
    assert body["previous_virtual_clock_time"].startswith(before.isoformat()[:16])
    assert clock.now() != before


def test_advance_clock_rejects_zero_movement(api_client, api_prefix):
    response = api_client.post(f"{api_prefix}/simulate/advance-clock", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_read_clock_endpoint(api_client, api_prefix, clock):
    response = api_client.get(f"{api_prefix}/simulate/clock")
    assert response.status_code == 200
    assert response.json()["virtual_clock_time"].startswith(clock.now().isoformat()[:16])


def test_health_reports_simulation_time(api_client, clock):
    """Requirement 24.1."""
    body = api_client.get("/health").json()
    assert body["virtual_clock_time"].startswith(clock.now().isoformat()[:16])
