"""Centralized audit logging.

Every meaningful decision in the system passes through ``record()``. This is the
only module that constructs ``AuditEvent`` rows (Requirement 19.6), and it exposes
no update or delete path, so the trail is append-only by construction
(Requirement 19.5).

Each event answers six questions: what happened (``event_type``, ``message``), why
(``metadata``), what initiated it (``stage`` plus ``workflow_id``), what was decided
(decision metadata), what the policy allowed (``policy_rule_id``, ``policy_reason``),
and what the outcome was (outcome metadata).

Nothing recorded here identifies a payment instrument or a customer's contact
details; payment method is carried as a method type only (Requirement 19.8).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.enums import AuditEventType, WorkflowStage
from app.core.logging import get_logger
from app.db.base import new_id
from app.models import AuditEvent

logger = get_logger("audit")

#: Metadata keys that must never appear on an audit event.
FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "card_number",
        "pan",
        "cvv",
        "expiry",
        "upi_id",
        "vpa",
        "email",
        "phone",
        "contact",
        "address",
        "customer_email",
        "customer_phone",
    }
)


class AuditService:
    """Append-only writer and reader of the decision trail."""

    def __init__(self, session: Session, clock: VirtualClock) -> None:
        self._session = session
        self._clock = clock

    # -- writing -----------------------------------------------------------

    def record(
        self,
        *,
        case_id: str,
        payment_id: str,
        stage: WorkflowStage,
        event_type: AuditEventType,
        message: str,
        metadata: dict[str, Any] | None = None,
        workflow_id: str | None = None,
    ) -> AuditEvent:
        """Append one audit event and return it.

        ``workflow_id`` is stored inside the metadata, which is what makes a
        complete workflow run reconstructable from the database without a separate
        table (Requirement 23.1).
        """
        payload = self._sanitise(metadata or {})
        if workflow_id is not None:
            payload["workflow_id"] = workflow_id

        event = AuditEvent(
            event_id=new_id("evt"),
            case_id=case_id,
            payment_id=payment_id,
            stage=stage,
            event_type=event_type,
            message=message,
            meta=payload,
            sequence=self._next_sequence(case_id),
            timestamp=self._clock.now(),
        )
        self._session.add(event)
        self._session.flush()

        logger.info(
            "audit | %s | case=%s | stage=%s | %s",
            event_type.value,
            case_id,
            stage.value,
            message,
        )
        return event

    def _next_sequence(self, case_id: str) -> int:
        """Next ordering key for this case."""
        statement = select(func.coalesce(func.max(AuditEvent.sequence), 0)).where(
            AuditEvent.case_id == case_id
        )
        return int(self._session.execute(statement).scalar_one()) + 1

    @staticmethod
    def _sanitise(metadata: dict[str, Any]) -> dict[str, Any]:
        """Drop any key that could carry sensitive data (Requirement 19.8)."""
        return {
            key: value
            for key, value in metadata.items()
            if key.lower() not in FORBIDDEN_METADATA_KEYS
        }

    # -- reading -----------------------------------------------------------

    def for_case(self, case_id: str) -> list[AuditEvent]:
        """Every event for a case, oldest first (Requirement 19.7)."""
        statement = (
            select(AuditEvent)
            .where(AuditEvent.case_id == case_id)
            .order_by(AuditEvent.timestamp.asc(), AuditEvent.sequence.asc())
        )
        return list(self._session.execute(statement).scalars().all())

    def for_payment(self, payment_id: str) -> list[AuditEvent]:
        """Every event for a payment across all of its cases."""
        statement = (
            select(AuditEvent)
            .where(AuditEvent.payment_id == payment_id)
            .order_by(AuditEvent.timestamp.asc(), AuditEvent.sequence.asc())
        )
        return list(self._session.execute(statement).scalars().all())

    def event_types_for_case(self, case_id: str) -> list[AuditEventType]:
        """Event types for a case in order. Convenient for assertions and demos."""
        return [event.event_type for event in self.for_case(case_id)]

    def count_for_case(self, case_id: str) -> int:
        statement = (
            select(func.count()).select_from(AuditEvent).where(AuditEvent.case_id == case_id)
        )
        return int(self._session.execute(statement).scalar_one())
