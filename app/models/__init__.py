"""RevivePay persistence models.

The original seven recovery-domain models remain stable. Phase 4 adds separate
operational job/outbox records so background infrastructure never changes the
recovery decision model.
"""

from app.db.base import Base
from app.models.audit_event import AuditEvent
from app.models.background_job import BackgroundJob
from app.models.customer import Customer
from app.models.gateway_payment import GatewayPayment
from app.models.gateway_webhook_event import GatewayWebhookEvent
from app.models.outbox_event import OutboxEvent
from app.models.payment import Payment
from app.models.payment_attempt import PaymentAttempt
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import RecoveryCase
from app.models.recovery_outcome import RecoveryOutcome

ALL_MODELS = (Customer, Payment, PaymentAttempt, RecoveryCase, RecoveryAction, RecoveryOutcome, AuditEvent, BackgroundJob, OutboxEvent, GatewayPayment, GatewayWebhookEvent)
LEGACY_DOMAIN_MODELS = ALL_MODELS[:7]

__all__ = ["ALL_MODELS", "LEGACY_DOMAIN_MODELS", "AuditEvent", "BackgroundJob", "Base", "Customer", "GatewayPayment", "GatewayWebhookEvent", "OutboxEvent", "Payment", "PaymentAttempt", "RecoveryAction", "RecoveryCase", "RecoveryOutcome"]
