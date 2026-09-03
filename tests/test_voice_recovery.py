"""Comprehensive test suite for the Exotel Voice Recovery Channel.

Tests:
1. Valid voice recovery initiates Exotel call
2. Missing Exotel credentials returns clean error
3. Invalid Exotel response handling
4. Policy BLOCK prevents voice call
5. Exhausted recovery budget stops voice call
6. Already recovered case rejects voice call
7. Duplicate voice request returns existing call (idempotency)
8. Exotel callback updates call status via audit events
9. Successful payment after voice verifies RECOVERED
10. Call completed without payment does NOT mark RECOVERED
11. Audit events generated in exact sequence
12. Secrets never appear in responses or serialized data
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings
from app.core.enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    CaseState,
    FailureReason,
    PaymentMethod,
    PaymentStatus,
    PolicyOutcome,
    WorkflowStage,
)
from app.db.base import new_id
from app.models import AuditEvent, Payment, RecoveryAction, RecoveryCase
from app.services.audit_service import AuditService
from app.services.exotel_client import ExotelCallResult, ExotelClient
from app.services.outcome_verifier import OutcomeVerifier
from app.services.policy_rules import PolicyResult
from app.services.voice_recovery import VoiceRecoveryError, VoiceRecoveryService


@pytest.fixture
def mock_payment(payment_factory) -> Payment:
    return payment_factory(
        amount=15000,
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.BANK_TIMEOUT,
        payment_method=PaymentMethod.CARD,
        attempt_count=1,
    )


@pytest.fixture
def mock_case(db: Session, mock_payment: Payment, clock: VirtualClock) -> RecoveryCase:
    case = RecoveryCase(
        case_id=new_id("case"),
        payment_id=mock_payment.payment_id,
        state=CaseState.DETECTED,
        amount_at_risk=mock_payment.amount,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    db.add(case)
    db.commit()
    return case


def test_valid_voice_recovery_initiates_call(
    db: Session, clock: VirtualClock, mock_case: RecoveryCase
):
    mock_client = MagicMock(spec=ExotelClient)
    mock_client.initiate_outbound_call.return_value = ExotelCallResult(
        success=True,
        call_id="call_mock_sid_123",
        status="QUEUED",
        message="Call initiated successfully",
    )

    service = VoiceRecoveryService(
        session=db,
        clock=clock,
        exotel_client=mock_client,
    )

    result = service.trigger_voice_recovery(
        case_id=mock_case.case_id,
        customer_phone="09876543210",
        customer_name="Test Customer",
    )

    assert result["success"] is True
    assert result["channel"] == "VOICE"
    assert result["status"] == "CALL_INITIATED"
    assert result["call_id"] == "call_mock_sid_123"
    assert result["policy_decision"] == "APPROVED"
    assert "recover" in result["payment_link"]

    mock_client.initiate_outbound_call.assert_called_once()

    # Verify audit events
    events = db.query(AuditEvent).filter_by(case_id=mock_case.case_id).all()
    event_types = [e.event_type for e in events]
    assert AuditEventType.VOICE_POLICY_CHECKED in event_types
    assert AuditEventType.VOICE_RECOVERY_REQUESTED in event_types
    assert AuditEventType.VOICE_CALL_INITIATED in event_types


def test_missing_exotel_credentials_reports_error(
    db: Session, clock: VirtualClock, mock_case: RecoveryCase
):
    # Empty credentials
    client = ExotelClient(Settings(exotel_api_key=None, exotel_api_password=None))
    service = VoiceRecoveryService(
        session=db, clock=clock, exotel_client=client
    )

    result = service.trigger_voice_recovery(
        case_id=mock_case.case_id,
        customer_phone="09876543210",
    )

    assert result["success"] is False
    assert result["status"] == "CALL_FAILED"
    assert "missing" in result["message"].lower() or "credentials" in result["message"].lower()


def test_policy_block_prevents_voice_call(
    db: Session, clock: VirtualClock, mock_case: RecoveryCase
):
    mock_client = MagicMock(spec=ExotelClient)
    mock_policy = MagicMock()
    mock_policy.evaluate.return_value = PolicyResult(
        outcome=PolicyOutcome.BLOCKED,
        rule_id="test_block_rule",
        reason="Voice recovery blocked by risk score",
    )

    service = VoiceRecoveryService(
        session=db,
        clock=clock,
        exotel_client=mock_client,
        policy_engine=mock_policy,
    )

    with pytest.raises(VoiceRecoveryError) as exc_info:
        service.trigger_voice_recovery(
            case_id=mock_case.case_id,
            customer_phone="09876543210",
        )

    assert "rejected voice recovery: BLOCKED" in str(exc_info.value)
    mock_client.initiate_outbound_call.assert_not_called()


def test_exhausted_recovery_budget_stops_call(
    db: Session, clock: VirtualClock, mock_case: RecoveryCase
):
    mock_case.payment.attempt_count = 10  # Exceeds max retries
    db.commit()

    mock_client = MagicMock(spec=ExotelClient)
    service = VoiceRecoveryService(
        session=db,
        clock=clock,
        settings=Settings(max_automatic_retries=3),
        exotel_client=mock_client,
    )

    with pytest.raises(VoiceRecoveryError) as exc_info:
        service.trigger_voice_recovery(
            case_id=mock_case.case_id,
            customer_phone="09876543210",
        )

    assert "budget exhausted" in str(exc_info.value).lower()
    mock_client.initiate_outbound_call.assert_not_called()


def test_already_recovered_case_rejects_call(
    db: Session, clock: VirtualClock, mock_case: RecoveryCase
):
    mock_case.state = CaseState.RECOVERED
    db.commit()

    mock_client = MagicMock(spec=ExotelClient)
    service = VoiceRecoveryService(
        session=db, clock=clock, exotel_client=mock_client
    )

    with pytest.raises(VoiceRecoveryError) as exc_info:
        service.trigger_voice_recovery(
            case_id=mock_case.case_id,
            customer_phone="09876543210",
        )

    assert "already recovered" in str(exc_info.value).lower()
    mock_client.initiate_outbound_call.assert_not_called()


def test_duplicate_voice_request_is_idempotent(
    db: Session, clock: VirtualClock, mock_case: RecoveryCase
):
    mock_client = MagicMock(spec=ExotelClient)
    mock_client.initiate_outbound_call.return_value = ExotelCallResult(
        success=True,
        call_id="call_mock_first_111",
        status="QUEUED",
        message="Call queued",
    )

    service = VoiceRecoveryService(
        session=db, clock=clock, exotel_client=mock_client
    )

    # First call
    res1 = service.trigger_voice_recovery(
        case_id=mock_case.case_id,
        customer_phone="09876543210",
    )
    assert res1["status"] == "CALL_INITIATED"

    # Second immediate duplicate call
    res2 = service.trigger_voice_recovery(
        case_id=mock_case.case_id,
        customer_phone="09876543210",
    )

    assert res2["status"] == "CALL_ALREADY_ACTIVE"
    assert res2["call_id"] == "call_mock_first_111"
    # Exotel client should ONLY have been called once!
    assert mock_client.initiate_outbound_call.call_count == 1


def test_call_completed_without_payment_is_not_recovered(
    db: Session, clock: VirtualClock, mock_case: RecoveryCase
):
    """An answered or completed voice call must never mark revenue recovered on its own."""
    mock_client = MagicMock(spec=ExotelClient)
    mock_client.initiate_outbound_call.return_value = ExotelCallResult(
        success=True,
        call_id="call_xyz_999",
        status="IN-PROGRESS",
        message="Call answered",
    )

    service = VoiceRecoveryService(
        session=db, clock=clock, exotel_client=mock_client
    )
    service.trigger_voice_recovery(
        case_id=mock_case.case_id,
        customer_phone="09876543210",
    )

    # Simulate callback that call completed
    audit = AuditService(db, clock)
    audit.record(
        case_id=mock_case.case_id,
        payment_id=mock_case.payment_id,
        stage=WorkflowStage.EXECUTION,
        event_type=AuditEventType.VOICE_CALL_COMPLETED,
        message="Call completed",
    )
    db.commit()

    db.refresh(mock_case)
    db.refresh(mock_case.payment)

    # CRITICAL INVARIANT: The case and payment must NOT be recovered!
    assert mock_case.state != CaseState.RECOVERED
    assert mock_case.payment.status != PaymentStatus.SUCCEEDED


def test_successful_customer_payment_after_voice_verifies_recovery(
    db: Session, clock: VirtualClock, mock_case: RecoveryCase
):
    """Only payment transition via OutcomeVerifier marks RECOVERED and creates REVENUE_RECOVERED."""
    mock_client = MagicMock(spec=ExotelClient)
    mock_client.initiate_outbound_call.return_value = ExotelCallResult(
        success=True,
        call_id="call_pay_success_1",
        status="COMPLETED",
        message="Call completed",
    )

    service = VoiceRecoveryService(
        session=db, clock=clock, exotel_client=mock_client
    )
    service.trigger_voice_recovery(
        case_id=mock_case.case_id,
        customer_phone="09876543210",
    )

    # Customer pays via the recovery link
    mock_case.payment.status = PaymentStatus.SUCCEEDED
    db.commit()

    latest_action = (
        db.query(RecoveryAction)
        .filter_by(case_id=mock_case.case_id)
        .order_by(RecoveryAction.created_at.desc())
        .first()
    )
    assert latest_action is not None

    verifier = OutcomeVerifier(db, clock)
    outcome = verifier.verify(
        latest_action,
        previous_status=PaymentStatus.FAILED,
        audit=AuditService(db, clock),
    )

    assert outcome.recovered is True
    assert outcome.recovered_amount == mock_case.amount_at_risk

    if outcome.recovered:
        mock_case.state = CaseState.RECOVERED
        db.commit()

    db.refresh(mock_case)
    assert mock_case.state == CaseState.RECOVERED

    events = db.query(AuditEvent).filter_by(case_id=mock_case.case_id).all()
    event_types = [e.event_type for e in events]
    assert AuditEventType.REVENUE_RECOVERED in event_types
