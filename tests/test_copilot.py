"""Tests for AI Recovery Copilot service and provider abstraction."""

from __future__ import annotations

import pytest
from app.core.enums import ActionType, FailureReason, PaymentStatus
from app.services.context_builder import RecoveryContextBuilder
from app.services.copilot import (
    AICopilotService,
    CopilotAnalysis,
    LocalMockCopilotProvider,
)


def test_local_mock_copilot_analysis(db, clock, settings, payment_factory):
    payment = payment_factory(
        amount=1_000_000,
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.BANK_TIMEOUT,
        attempt_count=1,
    )
    from app.services.risk_detector import RiskDetector
    from app.services.audit_service import AuditService

    risk_detector = RiskDetector(db, clock, AuditService(db, clock))
    case = risk_detector.detect_and_open_case(payment)
    assert case is not None

    context = RecoveryContextBuilder(db, clock).build(case)
    service = AICopilotService(settings=settings)

    res = service.analyze(context)
    assert isinstance(res, CopilotAnalysis)
    assert res.root_cause == FailureReason.BANK_TIMEOUT.value
    assert res.recommended_action == ActionType.RETRY_LATER
    assert res.confidence > 0.0
    assert not res.fallback_used
    assert res.provider_name == "local_mock_copilot"


class FailingProvider:
    provider_name = "failing_provider"

    def analyze(self, context):
        raise RuntimeError("Simulated API connection failure")


def test_copilot_fallback_behavior(db, clock, settings, payment_factory):
    payment = payment_factory(
        amount=100_000,
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.EXPIRED_CARD,
        attempt_count=1,
    )
    from app.services.risk_detector import RiskDetector
    from app.services.audit_service import AuditService

    case = RiskDetector(db, clock, AuditService(db, clock)).detect_and_open_case(payment)
    assert case is not None

    context = RecoveryContextBuilder(db, clock).build(case)

    service = AICopilotService(provider=FailingProvider(), settings=settings)
    res = service.analyze(context)

    assert res.fallback_used
    assert "deterministic_fallback" in res.provider_name
    assert "Simulated API connection failure" in (res.fallback_reason or "")
    assert res.recommended_action in (ActionType.CHANGE_PAYMENT_METHOD, ActionType.SEND_PAYMENT_LINK, ActionType.RETRY_LATER)
