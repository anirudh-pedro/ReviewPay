"""Narrow Razorpay HTTP adapter and signature helpers.

The adapter uses only the Python standard library so the deterministic simulator
keeps its existing dependency set. Tests inject the protocol below and never
contact Razorpay.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import Settings


class RazorpayProviderError(RuntimeError):
    """A provider response or transport failure safe to expose only generically."""


class RazorpayGateway(Protocol):
    """The small provider surface required by the sandbox gateway service."""

    def create_order(
        self, *, amount: int, currency: str, receipt: str, notes: dict[str, str]
    ) -> dict[str, Any]: ...

    def fetch_payment(self, provider_payment_id: str) -> dict[str, Any]: ...

    def fetch_order(self, provider_order_id: str) -> dict[str, Any]: ...


def verify_checkout_signature(
    *, order_id: str, payment_id: str, signature: str, key_secret: str
) -> bool:
    """Verify Razorpay Checkout's order/payment HMAC with constant-time comparison."""
    expected = hmac.new(
        key_secret.encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(*, raw_body: bytes, signature: str, webhook_secret: str) -> bool:
    """Verify a Razorpay webhook over its exact, unparsed request bytes."""
    expected = hmac.new(webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class RazorpayHttpClient:
    """Minimal authenticated HTTP implementation of :class:`RazorpayGateway`."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_order(
        self, *, amount: int, currency: str, receipt: str, notes: dict[str, str]
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/orders",
            {"amount": amount, "currency": currency, "receipt": receipt, "notes": notes},
        )

    def fetch_payment(self, provider_payment_id: str) -> dict[str, Any]:
        return self._request("GET", f"/payments/{provider_payment_id}")

    def fetch_order(self, provider_order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/orders/{provider_order_id}")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        key_id = self._settings.razorpay_key_id
        key_secret = self._settings.razorpay_key_secret
        if not key_id or not key_secret:
            raise RazorpayProviderError("Razorpay credentials are not configured.")

        body = json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload else None
        credentials = base64.b64encode(f"{key_id}:{key_secret}".encode("utf-8")).decode("ascii")
        request = Request(
            f"{self._settings.razorpay_api_base_url.rstrip('/')}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {credentials}",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            with urlopen(request, timeout=self._settings.razorpay_timeout_seconds) as response:  # noqa: S310 - configured HTTPS URL
                decoded = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            raise RazorpayProviderError("Razorpay request failed.") from error

        if not isinstance(decoded, dict):
            raise RazorpayProviderError("Razorpay response was not an object.")
        return decoded


__all__ = [
    "RazorpayGateway",
    "RazorpayHttpClient",
    "RazorpayProviderError",
    "verify_checkout_signature",
    "verify_webhook_signature",
]
