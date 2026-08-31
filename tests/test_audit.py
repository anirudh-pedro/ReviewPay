"""Audit service tests (Requirement 19.2, 19.5-19.8)."""

from __future__ import annotations

import inspect

import pytest

from app.core.enums import AuditEventType, CaseState, WorkflowStage
from app.models import AuditEvent, RecoveryCase
from app.services.audit_service import FORBIDDEN_METADATA_KEYS, AuditService


@pytest.fixture
def audit(db, clock) -> AuditService:
    return AuditService(session=db, clock=clock)


@pytest.fixture
def case(db, payment_factory, clock) -> RecoveryCase:
    payment = payment_factory()
    now = clock.now()
    record = RecoveryCase(
        case_id="case_audit_0001",
        payment_id=payment.payment_id,
        state=CaseState.DETECTED,
        amount_at_risk=payment.amount,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.commit()
    return record


def _record(audit: AuditService, case: RecoveryCase, event_type: AuditEventType, **kwargs):
    return audit.record(
        case_id=case.case_id,
        payment_id=case.payment_id,
        stage=kwargs.pop("stage", WorkflowStage.DETECTION),
        event_type=event_type,
        message=kwargs.pop("message", "test event"),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Field completeness
# ---------------------------------------------------------------------------


def test_recorded_event_carries_every_required_field(audit, case, clock):
    """Requirement 19.2."""
    event = _record(
        audit,
        case,
        AuditEventType.REVENUE_RISK_DETECTED,
        stage=WorkflowStage.DETECTION,
        message="Revenue at risk detected.",
        metadata={"amount_at_risk": 1_000_000},
        workflow_id="wf_0001",
    )

    assert event.event_id.startswith("evt_")
    assert event.case_id == case.case_id
    assert event.payment_id == case.payment_id
    assert event.stage is WorkflowStage.DETECTION
    assert event.event_type is AuditEventType.REVENUE_RISK_DETECTED
    assert event.message == "Revenue at risk detected."
    assert event.meta["amount_at_risk"] == 1_000_000
    assert event.timestamp == clock.now()


def test_workflow_id_is_stored_in_metadata(audit, case):
    """Requirement 23.1: the workflow record is reconstructable from audit rows."""
    event = _record(audit, case, AuditEventType.DIAGNOSIS_COMPLETED, workflow_id="wf_abc")
    assert event.meta["workflow_id"] == "wf_abc"
    assert event.workflow_id == "wf_abc"


def test_decision_metadata_is_preserved(audit, case):
    """Requirement 19.3."""
    metadata = {
        "model_version": "deterministic-scorer-v1",
        "probability": 0.776,
        "confidence": 1.0,
        "expected_recovery_value": 764_000,
        "selected_action": "RETRY_LATER",
        "alternatives": [{"action": "RETRY_NOW", "expected_recovery_value": 345_500}],
        "explanation": "highest expected recovery value",
    }
    event = _record(
        audit, case, AuditEventType.RECOVERY_DECISION_SELECTED, metadata=metadata
    )
    for key, value in metadata.items():
        assert event.meta[key] == value


def test_policy_metadata_is_preserved(audit, case):
    """Requirement 19.4."""
    event = _record(
        audit,
        case,
        AuditEventType.POLICY_BLOCKED,
        stage=WorkflowStage.POLICY,
        metadata={"policy_rule_id": "retry_limit_reached", "policy_reason": "limit hit"},
    )
    assert event.meta["policy_rule_id"] == "retry_limit_reached"
    assert event.meta["policy_reason"] == "limit hit"


# ---------------------------------------------------------------------------
# Ordering and append-only behaviour
# ---------------------------------------------------------------------------


def test_events_are_returned_oldest_first(audit, case, clock):
    """Requirement 19.7."""
    _record(audit, case, AuditEventType.REVENUE_RISK_DETECTED, message="first")
    clock.advance(minutes=5)
    _record(audit, case, AuditEventType.DIAGNOSIS_COMPLETED, message="second")

    assert [event.message for event in audit.for_case(case.case_id)] == ["first", "second"]


def test_ordering_is_stable_when_timestamps_tie(audit, case):
    """Several stages of one run share a simulation timestamp."""
    expected = [
        AuditEventType.REVENUE_RISK_DETECTED,
        AuditEventType.DIAGNOSIS_COMPLETED,
        AuditEventType.RECOVERY_OPTIONS_EVALUATED,
        AuditEventType.RECOVERY_DECISION_SELECTED,
        AuditEventType.POLICY_APPROVED,
        AuditEventType.ACTION_EXECUTED,
        AuditEventType.OUTCOME_VERIFIED,
    ]
    for event_type in expected:
        _record(audit, case, event_type)

    recorded = audit.for_case(case.case_id)
    assert [event.event_type for event in recorded] == expected
    assert [event.sequence for event in recorded] == list(range(1, len(expected) + 1))
    # All share one simulation timestamp, proving the tiebreak did the work.
    assert len({event.timestamp for event in recorded}) == 1


def test_sequence_is_per_case(db, audit, case, payment_factory, clock):
    other_payment = payment_factory()
    other = RecoveryCase(
        case_id="case_audit_0002",
        payment_id=other_payment.payment_id,
        state=CaseState.DETECTED,
        amount_at_risk=other_payment.amount,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    db.add(other)
    db.commit()

    _record(audit, case, AuditEventType.REVENUE_RISK_DETECTED)
    _record(audit, case, AuditEventType.DIAGNOSIS_COMPLETED)
    first_other = _record(audit, other, AuditEventType.REVENUE_RISK_DETECTED)

    assert first_other.sequence == 1


def test_service_exposes_no_update_or_delete_path():
    """Requirement 19.5: the trail is append-only by construction."""
    names = {
        name
        for name, _ in inspect.getmembers(AuditService, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    for forbidden in ("update", "delete", "remove", "purge", "edit", "modify"):
        assert not any(forbidden in name for name in names), f"unexpected mutator: {names}"


def test_recording_never_modifies_an_existing_row(audit, case, db):
    first = _record(audit, case, AuditEventType.REVENUE_RISK_DETECTED, message="original")
    original_id = first.event_id
    _record(audit, case, AuditEventType.DIAGNOSIS_COMPLETED, message="later")
    db.commit()

    reread = db.get(AuditEvent, original_id)
    assert reread.message == "original"
    assert audit.count_for_case(case.case_id) == 2


# ---------------------------------------------------------------------------
# Sensitive data
# ---------------------------------------------------------------------------


def test_sensitive_metadata_keys_are_dropped(audit, case):
    """Requirement 19.8."""
    event = _record(
        audit,
        case,
        AuditEventType.ACTION_EXECUTED,
        metadata={
            "payment_method": "UPI",
            "card_number": "4111111111111111",
            "cvv": "123",
            "customer_email": "someone@example.test",
            "vpa": "someone@bank",
            "amount": 1_000_000,
        },
    )

    assert event.meta["payment_method"] == "UPI"
    assert event.meta["amount"] == 1_000_000
    for key in ("card_number", "cvv", "customer_email", "vpa"):
        assert key not in event.meta


def test_forbidden_key_list_covers_instrument_and_contact_fields():
    for key in ("card_number", "cvv", "email", "phone", "vpa"):
        assert key in FORBIDDEN_METADATA_KEYS


# ---------------------------------------------------------------------------
# Convenience reads
# ---------------------------------------------------------------------------


def test_event_types_for_case(audit, case):
    _record(audit, case, AuditEventType.REVENUE_RISK_DETECTED)
    _record(audit, case, AuditEventType.WORKFLOW_STOPPED)
    assert audit.event_types_for_case(case.case_id) == [
        AuditEventType.REVENUE_RISK_DETECTED,
        AuditEventType.WORKFLOW_STOPPED,
    ]


def test_for_payment_spans_cases(audit, case):
    _record(audit, case, AuditEventType.REVENUE_RISK_DETECTED)
    assert len(audit.for_payment(case.payment_id)) == 1
