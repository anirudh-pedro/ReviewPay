"""Provider-error normalization at the Razorpay boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.enums import FailureReason


def normalize_razorpay_failure(
    payload: Mapping[str, Any] | None, *, event_type: str | None = None
) -> FailureReason:
    """Map provider status/error vocabulary to RevivePay's stable failure reasons.

    Raw provider payloads never leave this function. The caller persists only the
    normalized reason and a small allowlisted provider summary.
    """
    values: list[str] = [event_type or ""]
    if payload:
        for key in ("error_code", "error_description", "reason", "status", "source"):
            value = payload.get(key)
            if isinstance(value, str):
                values.append(value)
        error = payload.get("error")
        if isinstance(error, Mapping):
            for key in ("code", "description", "reason", "source"):
                value = error.get(key)
                if isinstance(value, str):
                    values.append(value)

    text = " ".join(values).lower()
    if "subscription" in text or "recurring" in text:
        return FailureReason.SUBSCRIPTION_FAILURE
    if any(token in text for token in ("insufficient", "not enough balance", "low balance")):
        return FailureReason.INSUFFICIENT_FUNDS
    if any(token in text for token in ("expired", "expiry", "expiration")):
        return FailureReason.EXPIRED_CARD
    if any(token in text for token in ("timeout", "timed out", "bank_down")):
        return FailureReason.BANK_TIMEOUT
    if any(token in text for token in ("network", "connection", "gateway_error", "service_unavailable")):
        return FailureReason.NETWORK_ERROR
    if any(token in text for token in ("cancel", "dismiss", "abandon", "checkout", "expire")):
        return FailureReason.CHECKOUT_ABANDONMENT
    return FailureReason.UNKNOWN


__all__ = ["normalize_razorpay_failure"]
