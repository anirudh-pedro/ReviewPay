"""Authoritative persistence flow for Razorpay Sandbox checkout events.

Checkout browser values and signed webhooks are inputs, not payment truth. Every
state mutation below is based on a server-side provider retrieval after the
applicable signature has been verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import VirtualClock
from app.core.config import Settings
from app.core.enums import FailureReason, PaymentMethod, PaymentStatus
from app.core.errors import RecordNotFound, RevivePayError
from app.db.base import new_id
from app.integrations.razorpay import (
    RazorpayGateway,
    RazorpayProviderError,
    verify_checkout_signature,
    verify_webhook_signature,
)
from app.integrations.razorpay_failure_mapper import normalize_razorpay_failure
from app.models import GatewayPayment, GatewayWebhookEvent, Payment, RecoveryCase
from app.services.audit_service import AuditService
from app.services.payment_service import PaymentService
from app.services.risk_detector import RiskDetector


class GatewayNotConfigured(RevivePayError):
    code = "GATEWAY_NOT_CONFIGURED"
    http_status = 503

    def __init__(self) -> None:
        super().__init__("Razorpay Sandbox is not configured for this environment.")


class GatewayProviderUnavailable(RevivePayError):
    code = "GATEWAY_PROVIDER_UNAVAILABLE"
    http_status = 502

    def __init__(self) -> None:
        super().__init__("The payment gateway could not be verified at this time.")


class GatewaySignatureInvalid(RevivePayError):
    code = "GATEWAY_SIGNATURE_INVALID"
    http_status = 401

    def __init__(self) -> None:
        super().__init__("The gateway signature could not be verified.")


class GatewayStateMismatch(RevivePayError):
    code = "GATEWAY_STATE_MISMATCH"
    http_status = 409

    def __init__(self) -> None:
        super().__init__("The verified gateway state did not match the local order.")


@dataclass(frozen=True)
class GatewayOrder:
    mapping: GatewayPayment
    payment: Payment


@dataclass(frozen=True)
class GatewayApplicationResult:
    payment: Payment
    case: RecoveryCase | None
    provider_status: str
    changed: bool


@dataclass(frozen=True)
class GatewayWebhookResult:
    duplicate: bool
    known_payment: bool
    payment: Payment | None = None
    case: RecoveryCase | None = None


def _provider_method(value: object) -> PaymentMethod:
    normalized = str(value or "").lower()
    return {
        "card": PaymentMethod.CARD,
        "upi": PaymentMethod.UPI,
        "netbanking": PaymentMethod.NETBANKING,
        "wallet": PaymentMethod.WALLET,
        "emi": PaymentMethod.EMI,
    }.get(normalized, PaymentMethod.UPI)


def _provider_error_code(payload: Mapping[str, Any]) -> str | None:
    direct = payload.get("error_code")
    if isinstance(direct, str):
        return direct[:80]
    error = payload.get("error")
    if isinstance(error, Mapping) and isinstance(error.get("code"), str):
        return str(error["code"])[:80]
    return None


class GatewayPaymentService:
    """Coordinates Razorpay order mapping and verified payment state application."""

    provider = "razorpay"

    def __init__(
        self,
        session: Session,
        clock: VirtualClock,
        settings: Settings,
        client: RazorpayGateway,
    ) -> None:
        self._session = session
        self._clock = clock
        self._settings = settings
        self._client = client

    def create_order(
        self,
        *,
        amount: int,
        currency: str,
        customer_id: str | None,
        merchant_id: str,
        idempotency_key: str,
    ) -> GatewayOrder:
        self._require_checkout_configuration()
        existing = self._session.execute(
            select(GatewayPayment).where(GatewayPayment.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            return GatewayOrder(mapping=existing, payment=existing.payment)

        receipt = f"rvp-{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:32]}"
        try:
            provider_order = self._client.create_order(
                amount=amount,
                currency=currency,
                receipt=receipt,
                notes={"revivepay_mode": "sandbox"},
            )
        except RazorpayProviderError as error:
            raise GatewayProviderUnavailable() from error

        provider_order_id = provider_order.get("id")
        if not isinstance(provider_order_id, str) or not provider_order_id:
            raise GatewayProviderUnavailable()
        if provider_order.get("amount") != amount or provider_order.get("currency") != currency:
            raise GatewayStateMismatch()

        payment = PaymentService(self._session, self._clock).create_payment(
            amount=amount,
            currency=currency,
            payment_method=PaymentMethod.UPI,
            customer_id=customer_id,
            merchant_id=merchant_id,
            metadata={"gateway_provider": self.provider, "gateway_order_id": provider_order_id},
            is_synthetic=False,
            commit=False,
        )
        now = self._clock.now()
        mapping = GatewayPayment(
            gateway_payment_id=new_id("gwp"),
            provider=self.provider,
            payment_id=payment.payment_id,
            provider_order_id=provider_order_id,
            provider_payment_id=None,
            idempotency_key=idempotency_key,
            provider_status=(
                provider_order.get("status") if isinstance(provider_order.get("status"), str) else None
            ),
            created_at=now,
            updated_at=now,
        )
        self._session.add(mapping)
        self._session.flush()
        return GatewayOrder(mapping=mapping, payment=payment)

    def verify_checkout(
        self, *, order_id: str, payment_id: str, signature: str
    ) -> GatewayApplicationResult:
        self._require_checkout_configuration()
        mapping = self._mapping_for_order(order_id)
        if not verify_checkout_signature(
            order_id=order_id,
            payment_id=payment_id,
            signature=signature,
            key_secret=self._settings.razorpay_key_secret or "",
        ):
            raise GatewaySignatureInvalid()

        provider_order, provider_payment = self._retrieve_authoritative_state(
            mapping, payment_id
        )
        self._validate_provider_order(mapping, provider_order)
        return self._apply_authoritative_payment(
            mapping=mapping,
            provider_payment=provider_payment,
            event_type="checkout.callback",
        )

    def process_webhook(
        self, *, raw_body: bytes, signature: str | None, delivery_id: str | None
    ) -> GatewayWebhookResult:
        self._require_webhook_configuration()
        if not signature or not verify_webhook_signature(
            raw_body=raw_body,
            signature=signature,
            webhook_secret=self._settings.razorpay_webhook_secret or "",
        ):
            raise GatewaySignatureInvalid()

        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GatewaySignatureInvalid() from error
        if not isinstance(payload, dict) or not isinstance(payload.get("event"), str):
            raise GatewaySignatureInvalid()

        event_type = payload["event"]
        entity = self._webhook_payment_entity(payload)
        order_id = entity.get("order_id") if isinstance(entity.get("order_id"), str) else None
        payment_id = entity.get("id") if isinstance(entity.get("id"), str) else None
        digest = hashlib.sha256(raw_body).hexdigest()
        idempotency_key = f"{self.provider}:{delivery_id or digest}"
        existing = self._session.execute(
            select(GatewayWebhookEvent).where(
                GatewayWebhookEvent.idempotency_key == idempotency_key
            )
        ).scalar_one_or_none()
        if existing is not None:
            return GatewayWebhookResult(duplicate=True, known_payment=existing.provider_order_id is not None)

        now = self._clock.now()
        ledger = GatewayWebhookEvent(
            webhook_event_id=new_id("gwe"),
            provider=self.provider,
            delivery_id=delivery_id,
            idempotency_key=idempotency_key,
            raw_payload_sha256=digest,
            event_type=event_type,
            provider_order_id=order_id,
            provider_payment_id=payment_id,
            processing_status="RECEIVED",
            created_at=now,
            processed_at=None,
        )
        self._session.add(ledger)
        self._session.flush()

        mapping = self._mapping_for_webhook(order_id=order_id, payment_id=payment_id)
        if mapping is None:
            ledger.processing_status = "UNKNOWN_PAYMENT"
            ledger.processed_at = self._clock.now()
            self._session.flush()
            return GatewayWebhookResult(duplicate=False, known_payment=False)

        if not payment_id:
            ledger.processing_status = "IGNORED"
            ledger.processed_at = self._clock.now()
            self._session.flush()
            return GatewayWebhookResult(duplicate=False, known_payment=True, payment=mapping.payment)

        provider_order, provider_payment = self._retrieve_authoritative_state(mapping, payment_id)
        self._validate_provider_order(mapping, provider_order)
        applied = self._apply_authoritative_payment(
            mapping=mapping,
            provider_payment=provider_payment,
            event_type=event_type,
        )
        ledger.processing_status = "APPLIED" if applied.changed else "NO_CHANGE"
        ledger.processed_at = self._clock.now()
        self._session.flush()
        return GatewayWebhookResult(
            duplicate=False,
            known_payment=True,
            payment=applied.payment,
            case=applied.case,
        )

    def _retrieve_authoritative_state(
        self, mapping: GatewayPayment, payment_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            return (
                self._client.fetch_order(mapping.provider_order_id),
                self._client.fetch_payment(payment_id),
            )
        except RazorpayProviderError as error:
            raise GatewayProviderUnavailable() from error

    def _apply_authoritative_payment(
        self,
        *,
        mapping: GatewayPayment,
        provider_payment: Mapping[str, Any],
        event_type: str,
    ) -> GatewayApplicationResult:
        payment = mapping.payment
        provider_payment_id = provider_payment.get("id")
        if not isinstance(provider_payment_id, str) or not provider_payment_id:
            raise GatewayStateMismatch()
        if provider_payment.get("order_id") != mapping.provider_order_id:
            raise GatewayStateMismatch()
        if provider_payment.get("amount") != payment.amount or provider_payment.get("currency") != payment.currency:
            raise GatewayStateMismatch()

        provider_status = str(provider_payment.get("status") or "unknown").lower()
        failure_reason = normalize_razorpay_failure(provider_payment, event_type=event_type)
        if provider_status == "captured":
            payment_status = PaymentStatus.SUCCEEDED
            failure_reason = None
        elif provider_status == "failed":
            payment_status = (
                PaymentStatus.ABANDONED
                if failure_reason is FailureReason.CHECKOUT_ABANDONMENT
                else PaymentStatus.FAILED
            )
        else:
            payment_status = PaymentStatus.PENDING
            failure_reason = None

        if (
            mapping.provider_payment_id == provider_payment_id
            and payment.status is payment_status
            and mapping.provider_status == provider_status
        ):
            return GatewayApplicationResult(
                payment=payment, case=None, provider_status=provider_status, changed=False
            )

        already_claimed = self._session.execute(
            select(GatewayPayment).where(GatewayPayment.provider_payment_id == provider_payment_id)
        ).scalar_one_or_none()
        if already_claimed is not None and already_claimed.gateway_payment_id != mapping.gateway_payment_id:
            raise GatewayStateMismatch()

        mapping.provider_payment_id = provider_payment_id
        mapping.provider_status = provider_status
        mapping.updated_at = self._clock.now()
        payment.payment_method = _provider_method(provider_payment.get("method"))

        summary = {
            "provider": self.provider,
            "order_id": mapping.provider_order_id,
            "payment_id": provider_payment_id,
            "status": provider_status,
            "normalized_failure_reason": failure_reason.value if failure_reason else None,
            "error_code": _provider_error_code(provider_payment),
            "event_type": event_type,
        }
        attempt = PaymentService(self._session, self._clock).record_external_checkout_attempt(
            payment=payment,
            status=payment_status,
            failure_reason=failure_reason,
            provider_response=summary,
        )
        case = None
        if attempt is not None and payment.status in PaymentStatus.unsuccessful():
            case = RiskDetector(
                session=self._session,
                clock=self._clock,
                audit=AuditService(session=self._session, clock=self._clock),
            ).detect_and_open_case(payment)
        self._session.flush()
        return GatewayApplicationResult(
            payment=payment, case=case, provider_status=provider_status, changed=True
        )

    def _mapping_for_order(self, order_id: str) -> GatewayPayment:
        mapping = self._session.execute(
            select(GatewayPayment).where(
                GatewayPayment.provider == self.provider,
                GatewayPayment.provider_order_id == order_id,
            )
        ).scalar_one_or_none()
        if mapping is None:
            raise RecordNotFound("GatewayOrder", order_id)
        return mapping

    def _mapping_for_webhook(
        self, *, order_id: str | None, payment_id: str | None
    ) -> GatewayPayment | None:
        if order_id:
            mapping = self._session.execute(
                select(GatewayPayment).where(
                    GatewayPayment.provider == self.provider,
                    GatewayPayment.provider_order_id == order_id,
                )
            ).scalar_one_or_none()
            if mapping is not None:
                return mapping
        if payment_id:
            return self._session.execute(
                select(GatewayPayment).where(
                    GatewayPayment.provider == self.provider,
                    GatewayPayment.provider_payment_id == payment_id,
                )
            ).scalar_one_or_none()
        return None

    @staticmethod
    def _webhook_payment_entity(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        root = payload.get("payload")
        if not isinstance(root, Mapping):
            return {}
        payment = root.get("payment")
        if not isinstance(payment, Mapping):
            return {}
        entity = payment.get("entity")
        return entity if isinstance(entity, Mapping) else {}

    @staticmethod
    def _validate_provider_order(mapping: GatewayPayment, provider_order: Mapping[str, Any]) -> None:
        if provider_order.get("id") != mapping.provider_order_id:
            raise GatewayStateMismatch()
        if provider_order.get("amount") != mapping.payment.amount or provider_order.get("currency") != mapping.payment.currency:
            raise GatewayStateMismatch()

    def _require_checkout_configuration(self) -> None:
        if (
            not self._settings.razorpay_enabled
            or not self._settings.razorpay_key_id
            or not self._settings.razorpay_key_secret
        ):
            raise GatewayNotConfigured()

    def _require_webhook_configuration(self) -> None:
        if not self._settings.razorpay_enabled or not self._settings.razorpay_webhook_secret:
            raise GatewayNotConfigured()


__all__ = [
    "GatewayApplicationResult",
    "GatewayNotConfigured",
    "GatewayOrder",
    "GatewayPaymentService",
    "GatewayProviderUnavailable",
    "GatewaySignatureInvalid",
    "GatewayStateMismatch",
    "GatewayWebhookResult",
]
