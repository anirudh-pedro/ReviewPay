"""Command Center endpoint tests.

Covers the product surfaces added for the dashboard: overview, scenarios, autopilot,
Strategy Lab what-if, the baseline benchmark, and demo reset.

Two properties get the most attention, because they are what a judge is asked to
trust:

- Autopilot runs the **real** workflow, so its totals must equal what the analytics
  service independently computes from persisted rows.
- The safety invariants hold through the batch path too: an escalated case never
  executes, and an exhausted budget cannot be bypassed.
"""

from __future__ import annotations

import pytest

from app.core.enums import CaseState, FailureReason, PaymentStatus
from app.services.analytics_service import AnalyticsService
from app.services.audit_service import AuditService
from app.services.autopilot import AutopilotService
from app.services.risk_detector import RiskDetector
from app.services.scenario_generator import ScenarioGenerator


@pytest.fixture
def seeded(db, clock, settings):
    """The four deterministic demo scenarios, built by the real generator."""
    generator = ScenarioGenerator(session=db, clock=clock, settings=settings)
    scenarios = generator.generate_demo_scenarios()
    db.commit()
    return {scenario.key: scenario for scenario in scenarios}


@pytest.fixture
def open_case(db, clock, payment_factory):
    detector = RiskDetector(
        session=db, clock=clock, audit=AuditService(session=db, clock=clock)
    )

    def _make(*, amount=1_000_000, reason=FailureReason.BANK_TIMEOUT, attempts=1):
        payment = payment_factory(
            amount=amount,
            status=PaymentStatus.FAILED,
            failure_reason=reason,
            attempt_count=attempts,
        )
        case = detector.detect_and_open_case(payment)
        db.commit()
        return payment, case

    return _make


# ===========================================================================
# Overview
# ===========================================================================


def test_overview_returns_zeroed_payload_on_an_empty_database(api_client, api_prefix):
    response = api_client.get(f"{api_prefix}/recovery/overview")
    assert response.status_code == 200

    body = response.json()
    assert body["revenue_at_risk"] == {"amount": 0, "currency": "INR"}
    assert body["revenue_recovered"] == {"amount": 0, "currency": "INR"}
    assert body["recovery_rate"] == 0.0
    assert body["active_cases"] == 0
    assert body["by_failure_reason"] == []
    assert body["by_action"] == []


def test_overview_is_labelled_synthetic(api_client, api_prefix):
    body = api_client.get(f"{api_prefix}/recovery/overview").json()
    assert body["data_source"] == "synthetic_simulation"
    assert "no real money" in body["notice"].lower()


def test_overview_reports_the_registered_policy_rules(api_client, api_prefix, settings):
    """The safety panel must reflect real rules, not decorative claims."""
    safety = api_client.get(f"{api_prefix}/recovery/overview").json()["safety"]

    assert safety["recovery_budget_enforced"] is True
    assert safety["high_value_escalation_enabled"] is True
    assert "recovery_budget_exhausted" in safety["policy_rules"]
    assert "high_value_transaction" in safety["policy_rules"]
    assert safety["max_automatic_retries"] == settings.max_automatic_retries
    assert safety["high_value_threshold"]["amount"] == (
        settings.high_value_escalation_threshold
    )


def test_overview_matches_analytics_after_a_batch(api_client, api_prefix, db, seeded):
    """Requirement 20.4: figures are derived, never invented."""
    api_client.post(f"{api_prefix}/recovery/autopilot", json={})

    body = api_client.get(f"{api_prefix}/recovery/overview").json()
    revenue = AnalyticsService(db).revenue()

    assert body["revenue_at_risk"]["amount"] == revenue.revenue_at_risk
    assert body["revenue_recovered"]["amount"] == revenue.revenue_recovered
    assert body["recovery_rate"] == revenue.recovery_rate


def test_overview_breakdowns_populate_after_a_batch(api_client, api_prefix, seeded):
    api_client.post(f"{api_prefix}/recovery/autopilot", json={})
    body = api_client.get(f"{api_prefix}/recovery/overview").json()

    reasons = {item["failure_reason"] for item in body["by_failure_reason"]}
    assert "BANK_TIMEOUT" in reasons
    assert "EXPIRED_CARD" in reasons

    actions = {item["action_type"] for item in body["by_action"]}
    assert "RETRY_LATER" in actions

    for item in body["by_action"]:
        assert item["executed"] <= item["selected"]
        assert item["successes"] <= item["executed"]


def test_recovered_payments_stay_in_their_failure_reason_bucket(
    api_client, api_prefix, seeded
):
    """A recovered payment has its reason cleared, so the breakdown reads the diagnosis.

    Without that fallback every success would vanish from the breakdown and recovery
    would look worse than it actually was.
    """
    api_client.post(f"{api_prefix}/recovery/autopilot", json={})
    body = api_client.get(f"{api_prefix}/recovery/overview").json()

    expired = next(
        item
        for item in body["by_failure_reason"]
        if item["failure_reason"] == "EXPIRED_CARD"
    )
    assert expired["amount_recovered"]["amount"] > 0
    assert expired["recovered_cases"] >= 1


# ===========================================================================
# Scenarios
# ===========================================================================


def test_scenarios_endpoint_lists_the_four_demo_cases(api_client, api_prefix, seeded):
    body = api_client.get(f"{api_prefix}/recovery/scenarios").json()

    assert [item["key"] for item in body["scenarios"]] == ["A", "B", "C", "D"]
    assert [item["case_id"] for item in body["scenarios"]] == [
        "case_demo_a",
        "case_demo_b",
        "case_demo_c",
        "case_demo_d",
    ]


def test_scenarios_declare_their_expected_outcomes(api_client, api_prefix, seeded):
    scenarios = {
        item["key"]: item
        for item in api_client.get(f"{api_prefix}/recovery/scenarios").json()["scenarios"]
    }

    assert scenarios["A"]["expected_final_state"] == "RECOVERED"
    assert scenarios["A"]["requires_clock_advance"] is True
    assert scenarios["B"]["expected_final_state"] == "STOPPED"
    assert scenarios["C"]["expected_final_state"] == "ESCALATED"
    assert scenarios["D"]["expected_action"] == "CHANGE_PAYMENT_METHOD"


def test_scenarios_endpoint_is_empty_without_seed(api_client, api_prefix):
    assert api_client.get(f"{api_prefix}/recovery/scenarios").json()["scenarios"] == []


# ===========================================================================
# Autopilot
# ===========================================================================


def test_autopilot_drives_the_four_scenarios_to_their_expected_outcomes(
    api_client, api_prefix, seeded
):
    """The headline demo. Every outcome comes from the real workflow."""
    body = api_client.post(f"{api_prefix}/recovery/autopilot", json={}).json()
    results = {item["case_id"]: item for item in body["results"]}

    a = results["case_demo_a"]
    assert a["selected_action"] == "RETRY_LATER"
    assert a["policy_outcome"] == "APPROVED"
    assert a["final_state"] == CaseState.RECOVERED.value
    assert a["recovered_amount"]["amount"] == 1_000_000
    assert a["clock_advances"] >= 1  # a delayed retry needs the clock to move

    b = results["case_demo_b"]
    assert b["policy_outcome"] == "BLOCKED"
    assert b["final_state"] == CaseState.STOPPED.value
    assert b["recovered_amount"]["amount"] == 0

    c = results["case_demo_c"]
    assert c["policy_outcome"] == "ESCALATED"
    assert c["policy_rule_id"] == "high_value_transaction"
    assert c["final_state"] == CaseState.ESCALATED.value
    assert c["recovered_amount"]["amount"] == 0

    d = results["case_demo_d"]
    assert d["selected_action"] == "CHANGE_PAYMENT_METHOD"
    assert d["final_state"] == CaseState.RECOVERED.value
    assert d["recovered_amount"]["amount"] == 600_000


def test_autopilot_totals_equal_independently_computed_analytics(
    api_client, api_prefix, db, seeded
):
    """Batch totals are not a separate accounting of the same events."""
    body = api_client.post(f"{api_prefix}/recovery/autopilot", json={}).json()
    revenue = AnalyticsService(db).revenue()

    assert body["total_recovered"]["amount"] == revenue.revenue_recovered
    assert body["cases_recovered"] == revenue.cases_recovered


def test_autopilot_leaves_no_case_unresolved(api_client, api_prefix, seeded):
    body = api_client.post(f"{api_prefix}/recovery/autopilot", json={}).json()
    assert body["cases_unresolved"] == 0
    assert (
        body["cases_recovered"] + body["cases_stopped"] + body["cases_escalated"]
        == body["total_cases"]
    )


def test_autopilot_respects_the_limit(api_client, api_prefix, seeded):
    body = api_client.post(f"{api_prefix}/recovery/autopilot", json={"limit": 2}).json()
    assert body["total_cases"] == 2


def test_autopilot_rejects_an_invalid_limit(api_client, api_prefix):
    response = api_client.post(f"{api_prefix}/recovery/autopilot", json={"limit": 0})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_autopilot_is_idempotent_once_every_case_is_terminal(api_client, api_prefix, seeded):
    """A second batch finds nothing to do rather than double-counting."""
    first = api_client.post(f"{api_prefix}/recovery/autopilot", json={}).json()
    second = api_client.post(f"{api_prefix}/recovery/autopilot", json={}).json()

    assert first["total_cases"] > 0
    assert second["total_cases"] == 0
    assert second["total_recovered"]["amount"] == 0


def test_autopilot_exposes_per_case_step_progression(api_client, api_prefix, seeded):
    """The UI renders these steps, so each must carry its stage detail."""
    body = api_client.post(f"{api_prefix}/recovery/autopilot", json={}).json()
    case_a = next(item for item in body["results"] if item["case_id"] == "case_demo_a")

    assert len(case_a["steps"]) >= 2
    assert [step["run_index"] for step in case_a["steps"]] == list(
        range(1, len(case_a["steps"]) + 1)
    )
    assert any(step["stages"] for step in case_a["steps"])
    assert case_a["explanation"]
    assert case_a["alternatives"]


def test_autopilot_never_executes_an_escalated_case(api_client, api_prefix, seeded):
    """The safety invariant, verified through the batch path."""
    api_client.post(f"{api_prefix}/recovery/autopilot", json={})

    audit = api_client.get(f"{api_prefix}/recovery/cases/case_demo_c/audit").json()
    types = [event["event_type"] for event in audit["events"]]

    assert "POLICY_ESCALATED" in types
    assert "ACTION_EXECUTED" not in types
    assert "ACTION_FAILED" not in types
    assert "OUTCOME_VERIFIED" not in types


def test_autopilot_cannot_bypass_an_exhausted_recovery_budget(api_client, api_prefix, seeded):
    """No automatic action may run once the budget is spent."""
    api_client.post(f"{api_prefix}/recovery/autopilot", json={})

    audit = api_client.get(f"{api_prefix}/recovery/cases/case_demo_b/audit").json()
    types = [event["event_type"] for event in audit["events"]]

    assert "POLICY_BLOCKED" in types
    assert "WORKFLOW_STOPPED" in types
    assert "ACTION_EXECUTED" not in types

    blocked = next(
        event for event in audit["events"] if event["event_type"] == "POLICY_BLOCKED"
    )
    assert blocked["metadata"]["policy_rule_id"] in {
        "retry_limit_reached",
        "recovery_budget_exhausted",
    }


def test_autopilot_is_deterministic_across_reseeds(db, clock, settings):
    """Same seed, same batch outcome."""
    from sqlalchemy import delete

    from app.models import ALL_MODELS

    def run_once() -> tuple:
        for model in reversed(ALL_MODELS):
            db.execute(delete(model))
        db.commit()
        clock.reset()

        ScenarioGenerator(
            session=db, clock=clock, settings=settings
        ).generate_demo_scenarios()
        db.commit()

        batch = AutopilotService(session=db, clock=clock, settings=settings).run_batch()
        return tuple(
            (result.case_id, result.final_state.value, result.recovered_amount)
            for result in batch.results
        )

    assert run_once() == run_once()


# ===========================================================================
# Strategy Lab
# ===========================================================================


def test_simulate_values_every_comparable_strategy(api_client, api_prefix, seeded):
    body = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/simulate", json={}
    ).json()

    assert {option["action"] for option in body["options"]} == {
        "RETRY_NOW",
        "RETRY_LATER",
        "SEND_PAYMENT_LINK",
        "SEND_REMINDER",
        "CHANGE_PAYMENT_METHOD",
        "ESCALATE_HUMAN",
    }


def test_simulate_returns_the_full_erv_breakdown_per_option(api_client, api_prefix, seeded):
    """The UI shows probability, cost, friction, gross, and ERV; all come from here."""
    body = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/simulate", json={}
    ).json()

    for option in body["options"]:
        gross = option["gross_expected_recovery"]["amount"]
        cost = option["intervention_cost"]["amount"]
        friction = option["friction_penalty"]["amount"]
        assert option["expected_recovery_value"]["amount"] == gross - cost - friction
        assert 0.0 <= option["probability"] <= 1.0


def test_simulate_recommends_the_highest_eligible_expected_value(
    api_client, api_prefix, seeded
):
    body = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/simulate", json={}
    ).json()

    eligible = [option for option in body["options"] if option["eligible"]]
    best = max(eligible, key=lambda option: option["expected_recovery_value"]["amount"])

    assert body["recommended_action"] == best["action"]
    assert body["recommended_action"] == "RETRY_LATER"
    recommended = next(option for option in body["options"] if option["is_recommended"])
    assert recommended["action"] == "RETRY_LATER"


def test_simulate_explains_why_the_winner_won(api_client, api_prefix, seeded):
    reason = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/simulate", json={}
    ).json()["recommendation_reason"]

    assert "RETRY_LATER" in reason
    assert "expected recoverable revenue" in reason
    assert "policy" in reason.lower()


def test_simulate_ranks_retry_later_above_retry_now_for_bank_timeout(
    api_client, api_prefix, seeded
):
    body = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/simulate", json={}
    ).json()
    options = {option["action"]: option for option in body["options"]}

    assert options["RETRY_LATER"]["probability"] > options["RETRY_NOW"]["probability"]
    assert (
        options["RETRY_LATER"]["expected_recovery_value"]["amount"]
        > options["RETRY_NOW"]["expected_recovery_value"]["amount"]
    )


def test_simulate_includes_customer_context(api_client, api_prefix, seeded):
    customer = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/simulate", json={}
    ).json()["customer"]

    assert customer["customer_id"]
    assert customer["success_rate"] > 0
    assert customer["history_available"] is True


def test_simulate_marks_generated_candidates(api_client, api_prefix, seeded):
    """Non-candidates are still valued, so a judge can ask "why not that one?"."""
    options = {
        option["action"]: option
        for option in api_client.post(
            f"{api_prefix}/recovery/cases/case_demo_a/simulate", json={}
        ).json()["options"]
    }

    assert options["RETRY_LATER"]["is_candidate"] is True
    assert options["SEND_REMINDER"]["is_candidate"] is False


def test_simulate_overrides_change_policy_eligibility(api_client, api_prefix, seeded):
    """Zeroing the budget must block every automatic action, exempting escalation."""
    body = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/simulate",
        json={"max_automatic_retries": 0},
    ).json()

    options = {option["action"]: option for option in body["options"]}
    for action in (
        "RETRY_NOW",
        "RETRY_LATER",
        "SEND_PAYMENT_LINK",
        "SEND_REMINDER",
        "CHANGE_PAYMENT_METHOD",
    ):
        assert options[action]["eligible"] is False, action
        assert options[action]["policy_rule_id"] in {
            "retry_limit_reached",
            "recovery_budget_exhausted",
        }

    assert options["ESCALATE_HUMAN"]["eligible"] is True
    assert body["recommended_action"] == "ESCALATE_HUMAN"
    assert body["overrides_applied"] is True


def test_simulate_cost_override_changes_expected_value(api_client, api_prefix, seeded):
    """Economics are tunable through configuration, and only in the backend."""
    plain = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/simulate", json={}
    ).json()
    expensive = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/simulate",
        json={"intervention_cost_minor": {"RETRY_LATER": 500_000}},
    ).json()

    def erv(payload: dict, action: str) -> int:
        return next(
            option["expected_recovery_value"]["amount"]
            for option in payload["options"]
            if option["action"] == action
        )

    assert erv(expensive, "RETRY_LATER") < erv(plain, "RETRY_LATER")
    assert expensive["recommended_action"] != "RETRY_LATER"


def test_simulate_high_value_override_forces_escalation(api_client, api_prefix, seeded):
    options = {
        option["action"]: option
        for option in api_client.post(
            f"{api_prefix}/recovery/cases/case_demo_a/simulate",
            json={"high_value_escalation_threshold": 1},
        ).json()["options"]
    }

    assert options["RETRY_LATER"]["policy_outcome"] == "ESCALATED"
    assert options["RETRY_LATER"]["policy_rule_id"] == "high_value_transaction"


def test_simulate_does_not_mutate_state(api_client, api_prefix, db, seeded):
    """A what-if must never move money."""
    from app.models import Payment, RecoveryAction

    before_actions = db.query(RecoveryAction).count()
    payment = db.get(Payment, "pay_demo_a")
    before_status, before_attempts = payment.status, payment.attempt_count

    api_client.post(f"{api_prefix}/recovery/cases/case_demo_a/simulate", json={})

    db.expire_all()
    payment = db.get(Payment, "pay_demo_a")
    assert db.query(RecoveryAction).count() == before_actions
    assert payment.status is before_status
    assert payment.attempt_count == before_attempts


def test_simulate_returns_404_for_an_unknown_case(api_client, api_prefix):
    response = api_client.post(f"{api_prefix}/recovery/cases/case_missing/simulate", json={})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_simulate_rejects_a_negative_cost_override(api_client, api_prefix, seeded):
    response = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/simulate",
        json={"intervention_cost_minor": {"RETRY_LATER": -1}},
    )
    assert response.status_code == 422


def test_simulate_is_deterministic(api_client, api_prefix, seeded):
    first = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/simulate", json={}
    ).json()
    second = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/simulate", json={}
    ).json()

    assert first["options"] == second["options"]
    assert first["recommended_action"] == second["recommended_action"]


# ===========================================================================
# Baseline benchmark
# ===========================================================================


def test_baseline_comparison_favours_expected_value_selection(api_client, api_prefix, seeded):
    body = api_client.get(f"{api_prefix}/recovery/baseline").json()

    assert body["baseline"]["strategy"] == "Baseline"
    assert body["revivepay"]["strategy"] == "RevivePay"
    assert (
        body["revivepay"]["projected_recovered"]["amount"]
        > body["baseline"]["projected_recovered"]["amount"]
    )
    assert body["recovered_uplift"]["amount"] > 0
    assert body["recovery_rate_uplift_pct"] > 0


def test_baseline_uses_only_retry_now(api_client, api_prefix, seeded):
    """The baseline must be a genuinely naive strategy."""
    body = api_client.get(f"{api_prefix}/recovery/baseline").json()
    assert set(body["baseline"]["actions_used"]) <= {"RETRY_NOW"}


def test_revivepay_arm_uses_varied_actions(api_client, api_prefix, seeded):
    body = api_client.get(f"{api_prefix}/recovery/baseline").json()
    assert len(body["revivepay"]["actions_used"]) > 1


def test_baseline_survives_a_completed_batch(api_client, api_prefix, seeded):
    """Regression: the benchmark evaluates cases as first detected.

    Reading live payment state instead made both arms collapse to zero once Autopilot
    resolved the cases, which is precisely when a judge would look at it.
    """
    before = api_client.get(f"{api_prefix}/recovery/baseline").json()
    api_client.post(f"{api_prefix}/recovery/autopilot", json={})
    after = api_client.get(f"{api_prefix}/recovery/baseline").json()

    assert after["revivepay"]["projected_recovered"]["amount"] > 0
    assert (
        after["revivepay"]["projected_recovered"]
        == before["revivepay"]["projected_recovered"]
    )
    assert after["recovered_uplift"]["amount"] == before["recovered_uplift"]["amount"]


def test_baseline_is_labelled_a_synthetic_benchmark(api_client, api_prefix, seeded):
    body = api_client.get(f"{api_prefix}/recovery/baseline").json()
    assert "synthetic" in body["notice"].lower()
    assert body["data_source"] == "synthetic_simulation"


def test_baseline_is_deterministic(api_client, api_prefix, seeded):
    first = api_client.get(f"{api_prefix}/recovery/baseline").json()
    second = api_client.get(f"{api_prefix}/recovery/baseline").json()
    assert first["baseline"] == second["baseline"]
    assert first["revivepay"] == second["revivepay"]


# ===========================================================================
# Demo reset
# ===========================================================================


def test_demo_reset_restores_the_four_scenarios(api_client, api_prefix):
    response = api_client.post(f"{api_prefix}/demo/reset", json={"background_customers": 4})
    assert response.status_code == 200

    body = response.json()
    assert [item["key"] for item in body["scenarios"]] == ["A", "B", "C", "D"]
    assert body["cases"] > 0
    assert "No real payment data" in body["message"]


def test_demo_reset_rewinds_the_virtual_clock(api_client, api_prefix, settings):
    api_client.post(f"{api_prefix}/simulate/advance-clock", json={"hours": 5})
    body = api_client.post(f"{api_prefix}/demo/reset", json={}).json()

    assert body["virtual_clock_time"].startswith(
        settings.virtual_clock_start.isoformat()[:16]
    )


def test_demo_reset_clears_previous_recovery_results(api_client, api_prefix):
    """A reset must return the demo to a pre-run state, not accumulate on top."""
    api_client.post(f"{api_prefix}/demo/reset", json={"background_customers": 4})
    api_client.post(f"{api_prefix}/recovery/autopilot", json={})

    assert api_client.get(f"{api_prefix}/recovery/overview").json()[
        "revenue_recovered"
    ]["amount"] > 0

    api_client.post(f"{api_prefix}/demo/reset", json={"background_customers": 4})
    after = api_client.get(f"{api_prefix}/recovery/overview").json()

    assert after["revenue_recovered"]["amount"] == 0
    assert after["cases_recovered"] == 0
    assert after["active_cases"] > 0


def test_demo_reset_is_deterministic(api_client, api_prefix):
    """Same seed, same dataset, every time."""
    first = api_client.post(f"{api_prefix}/demo/reset", json={"background_customers": 6}).json()
    first_run = api_client.post(f"{api_prefix}/recovery/autopilot", json={}).json()

    second = api_client.post(f"{api_prefix}/demo/reset", json={"background_customers": 6}).json()
    second_run = api_client.post(f"{api_prefix}/recovery/autopilot", json={}).json()

    assert first["cases"] == second["cases"]
    assert first_run["total_at_risk"] == second_run["total_at_risk"]
    assert first_run["total_recovered"] == second_run["total_recovered"]
    assert first_run["recovery_rate"] == second_run["recovery_rate"]


def test_demo_reset_is_forbidden_outside_development(api_client, api_prefix, settings, monkeypatch):
    """A reset endpoint reachable in production would be a way to erase an audit trail."""
    from app.api.deps import settings_dep
    from app.core.config import Settings

    production = Settings(
        _env_file=None,
        environment="production",
        auth_mode="api_key",
        api_key="production-test-key",
        execution_mode="enqueue",
        virtual_clock_state_path=settings.virtual_clock_state_path,
    )
    api_client.app.dependency_overrides[settings_dep] = lambda: production

    response = api_client.post(
        f"{api_prefix}/demo/reset",
        json={},
        headers={"Authorization": "Bearer production-test-key"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "DEMO_RESET_FORBIDDEN"
    assert "production" in response.json()["error"]["message"]


# ===========================================================================
# Route registration
# ===========================================================================


def test_static_recovery_paths_are_not_shadowed_by_the_case_parameter(api_client, api_prefix):
    """``/recovery/overview`` must not be read as ``/recovery/cases/{case_id}``."""
    for path in ("overview", "scenarios", "baseline"):
        assert api_client.get(f"{api_prefix}/recovery/{path}").status_code == 200


def test_existing_endpoints_still_respond(api_client, api_prefix):
    """Phase 2 is additive: nothing previously served may break."""
    assert api_client.get("/health").status_code == 200
    assert api_client.get(f"{api_prefix}/payments").status_code == 200
    assert api_client.get(f"{api_prefix}/recovery/cases").status_code == 200
    assert api_client.get(f"{api_prefix}/analytics/revenue").status_code == 200
    assert api_client.get(f"{api_prefix}/analytics/recovery").status_code == 200
    assert api_client.get(f"{api_prefix}/simulate/clock").status_code == 200
