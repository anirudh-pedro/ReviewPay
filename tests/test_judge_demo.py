"""Tests for Judge Demo service and API endpoint."""

from __future__ import annotations

import pytest
from app.core.enums import FailureReason, PaymentStatus
from app.services.judge_demo_service import JudgeDemoService
from app.services.risk_detector import RiskDetector
from app.services.audit_service import AuditService


def test_judge_demo_service_pipeline(db, clock, settings, payment_factory):
    payment = payment_factory(
        amount=500_000,
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.BANK_TIMEOUT,
        attempt_count=1,
    )
    case = RiskDetector(db, clock, AuditService(db, clock)).detect_and_open_case(payment)
    assert case is not None
    db.commit()

    service = JudgeDemoService(db, clock, settings)
    result = service.run_judge_demo(case.case_id)

    assert result.case_id == case.case_id
    assert result.payment_id == payment.payment_id
    assert len(result.stages) == 8
    assert result.stages[0].label in ("REAL RAZORPAY SANDBOX", "SYNTHETIC SIMULATION")
    assert result.stages[1].label == "AI COPILOT ADVISORY"
    assert result.stages[4].label == "POLICY GATE - MANDATORY AUTHORITY"
    assert result.policy_outcome in ("APPROVED", "BLOCKED", "ESCALATED")


def test_judge_demo_api_endpoint(api_client, db, clock, payment_factory):
    payment = payment_factory(
        amount=250_000,
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.NETWORK_ERROR,
        attempt_count=1,
    )
    case = RiskDetector(db, clock, AuditService(db, clock)).detect_and_open_case(payment)
    assert case is not None
    db.commit()

    response = api_client.get(f"/api/recovery/cases/{case.case_id}/judge-demo")
    assert response.status_code == 200
    data = response.json()

    assert data["case_id"] == case.case_id
    assert "stages" in data
    assert len(data["stages"]) == 8
    assert data["stages"][0]["stage_number"] == 1
    assert data["stages"][7]["stage_number"] == 8
