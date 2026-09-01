"""Focused tests for the read-only Phase 3 Recovery Intelligence Layer.

The intelligence endpoints intentionally advise; they must not alter the recovery
workflow, create actions, record outcomes, or bypass the policy gate.
"""

from __future__ import annotations

import pytest

from app.core.enums import ActionType
from app.models import AuditEvent, Payment, RecoveryAction, RecoveryCase, RecoveryOutcome
from app.services.context_builder import RecoveryContextBuilder
from app.services.recovery_intelligence import StructuredDiagnosisAgent, context_at_detection
from app.services.scenario_generator import ScenarioGenerator


@pytest.fixture
def seeded(db, clock, settings):
    """Seed the canonical deterministic A-D scenarios for intelligence checks."""
    scenarios = ScenarioGenerator(session=db, clock=clock, settings=settings).generate_demo_scenarios()
    db.commit()
    return {scenario.key: scenario for scenario in scenarios}


def _persistence_counts(db) -> tuple[int, int, int, int]:
    return (
        db.query(Payment).count(),
        db.query(RecoveryAction).count(),
        db.query(RecoveryOutcome).count(),
        db.query(AuditEvent).count(),
    )


def _candidate(payload: dict, action: str) -> dict:
    return next(item for item in payload["candidates"] if item["action"] == action)


def test_get_intelligence_returns_explainable_synthetic_read_only_payload(
    api_client, api_prefix, db, seeded
):
    """The complete advisory contract is structured, policy-aware, and non-mutating."""
    before_counts = _persistence_counts(db)
    payment = db.get(Payment, "pay_demo_a")
    assert payment is not None
    before_status = payment.status
    before_attempts = payment.attempt_count

    response = api_client.get(f"{api_prefix}/recovery/cases/case_demo_a/intelligence")

    assert response.status_code == 200
    body = response.json()
    assert body["data_source"] == "synthetic_simulation"
    assert "synthetic" in body["notice"].lower()
    assert body["case_id"] == "case_demo_a"
    assert body["diagnosis"]["root_cause"] == "BANK_TIMEOUT"
    assert body["diagnosis"]["source"]
    assert "customer_context" in body["diagnosis"]
    assert body["model"]["model_version"] == "bounded-empirical-bayes-v1"
    assert body["model"]["training_samples"] >= body["model"]["synthetic_samples"]
    assert body["candidates"]

    recommended = [item for item in body["candidates"] if item["is_adaptive_recommended"]]
    assert len(recommended) == 1
    assert body["adaptive_recommended_action"] == recommended[0]["action"]
    assert recommended[0]["policy_outcome"] == "APPROVED"
    assert recommended[0]["learning_factors"]
    assert recommended[0]["historical_evidence"]["total_samples"] >= 0

    counterfactual = body["counterfactual"]
    assert counterfactual["basis"] == "detection_time_synthetic_projection"
    assert counterfactual["baseline"]["action"] == "RETRY_NOW"
    assert "no real payment" in counterfactual["notice"].lower()
    assert counterfactual["projected_recovered_uplift"]["amount"] == (
        counterfactual["revivepay"]["projected_recovered"]["amount"]
        - counterfactual["baseline"]["projected_recovered"]["amount"]
    )
    assert counterfactual["expected_recovery_value_uplift"]["amount"] == (
        counterfactual["revivepay"]["expected_recovery_value"]["amount"]
        - counterfactual["baseline"]["expected_recovery_value"]["amount"]
    )

    db.expire_all()
    payment = db.get(Payment, "pay_demo_a")
    assert payment is not None
    assert _persistence_counts(db) == before_counts
    assert payment.status is before_status
    assert payment.attempt_count == before_attempts


def test_intelligence_simulation_applies_overrides_without_mutating_state(
    api_client, api_prefix, db, seeded
):
    """Override economics belong to the backend and stay inside the read-only request."""
    before_counts = _persistence_counts(db)
    payment = db.get(Payment, "pay_demo_a")
    assert payment is not None
    before_status, before_attempts = payment.status, payment.attempt_count

    plain = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/intelligence/simulate", json={}
    )
    expensive = api_client.post(
        f"{api_prefix}/recovery/cases/case_demo_a/intelligence/simulate",
        json={"intervention_cost_minor": {"RETRY_LATER": 500_000}},
    )

    assert plain.status_code == 200
    assert expensive.status_code == 200
    plain_retry_later = _candidate(plain.json(), "RETRY_LATER")
    expensive_retry_later = _candidate(expensive.json(), "RETRY_LATER")
    assert expensive_retry_later["intervention_cost"]["amount"] == 500_000
    assert (
        expensive_retry_later["adaptive_expected_recovery_value"]["amount"]
        < plain_retry_later["adaptive_expected_recovery_value"]["amount"]
    )

    db.expire_all()
    payment = db.get(Payment, "pay_demo_a")
    assert payment is not None
    assert _persistence_counts(db) == before_counts
    assert payment.status is before_status
    assert payment.attempt_count == before_attempts


def test_intelligence_uses_only_policy_approved_actions_for_advisory_recommendation(
    api_client, api_prefix, seeded
):
    """A high-value escalation is never transformed into automatic advice."""
    response = api_client.get(f"{api_prefix}/recovery/cases/case_demo_c/intelligence")

    assert response.status_code == 200
    body = response.json()
    for candidate in body["candidates"]:
        if candidate["policy_outcome"] in {"BLOCKED", "ESCALATED"}:
            assert candidate["is_adaptive_recommended"] is False

    selected = [item for item in body["candidates"] if item["is_adaptive_recommended"]]
    assert len(selected) <= 1
    if selected:
        assert selected[0]["policy_outcome"] == "APPROVED"
        assert selected[0]["action"] in {"ESCALATE_HUMAN", "STOP"}
    else:
        assert body["adaptive_recommended_action"] is None


def test_verified_outcomes_are_bounded_evidence_not_online_state(
    api_client, api_prefix, seeded
):
    """Verified labels become visible on the next read, while repeated reads are stable."""
    before = api_client.get(f"{api_prefix}/recovery/cases/case_demo_a/intelligence")
    assert before.status_code == 200
    before_body = before.json()
    assert before_body["model"]["verified_outcome_samples"] == 0

    batch = api_client.post(f"{api_prefix}/recovery/autopilot", json={})
    assert batch.status_code == 200

    after = api_client.get(f"{api_prefix}/recovery/cases/case_demo_a/intelligence")
    repeated = api_client.get(f"{api_prefix}/recovery/cases/case_demo_a/intelligence")
    assert after.status_code == 200
    assert repeated.status_code == 200
    after_body = after.json()
    assert after_body["model"]["verified_outcome_samples"] > 0
    assert any(
        candidate["historical_evidence"]["verified_samples"] > 0
        for candidate in after_body["candidates"]
    )
    assert repeated.json()["model"] == after_body["model"]
    assert repeated.json()["candidates"] == after_body["candidates"]


def test_intelligence_returns_standard_not_found_for_unknown_case(api_client, api_prefix):
    response = api_client.get(f"{api_prefix}/recovery/cases/case_missing/intelligence")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_structured_diagnosis_falls_back_to_the_deterministic_diagnoser(
    db, clock, settings, seeded
):
    """A local agent failure preserves the deterministic diagnosis and provenance."""

    class BrokenDiagnoser:
        def diagnose(self, _context):
            raise RuntimeError("synthetic agent outage")

    case = db.get(RecoveryCase, "case_demo_a")
    assert case is not None
    context = context_at_detection(case, RecoveryContextBuilder(db, clock).build(case))

    diagnosis = StructuredDiagnosisAgent(BrokenDiagnoser()).analyze(
        context,
        recommended_action=ActionType.RETRY_LATER,
        high_value_threshold=settings.high_value_escalation_threshold,
    )

    assert diagnosis.fallback_used is True
    assert diagnosis.source == "deterministic_diagnosis_fallback"
    assert diagnosis.root_cause == "BANK_TIMEOUT"
    assert diagnosis.recommended_recovery_approach == "RETRY_LATER"
    assert diagnosis.fallback_reason is not None


@pytest.mark.parametrize(
    "suffix",
    ("prediction", "strategy-evaluation", "ai-diagnosis", "historical-insights", "decision-explanation"),
)
def test_focused_intelligence_routes_are_typed_read_only_aliases(
    api_client, api_prefix, db, seeded, suffix
):
    """Focused Phase 3 endpoints expose the same authoritative advisory payload."""

    before = _persistence_counts(db)
    response = api_client.get(f"{api_prefix}/recovery/cases/case_demo_a/{suffix}")

    assert response.status_code == 200
    assert response.json()["case_id"] == "case_demo_a"
    assert response.json()["data_source"] == "synthetic_simulation"
    assert _persistence_counts(db) == before


def test_model_status_exposes_only_safe_predictor_provenance(api_client, api_prefix):
    response = api_client.get(f"{api_prefix}/recovery/intelligence/model-status")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "deterministic_default"
    assert body["active_predictor"] == "deterministic-scorer-v1"
    assert body["feature_schema_version"] == "recovery-pre-action-v1"
    assert body["data_source"] == "synthetic_simulation"
