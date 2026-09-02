"""Tests for Sliding Window Rate Limiter and webhook payload limits."""

from __future__ import annotations

import pytest
from app.core.rate_limiter import RateLimitExceeded, SlidingWindowRateLimiter


def test_sliding_window_rate_limiter_allows_under_limit():
    limiter = SlidingWindowRateLimiter(requests_per_minute=5, window_seconds=60)
    for _ in range(5):
        limiter.check("client-1")


def test_sliding_window_rate_limiter_blocks_over_limit():
    limiter = SlidingWindowRateLimiter(requests_per_minute=3, window_seconds=60)
    limiter.check("client-2")
    limiter.check("client-2")
    limiter.check("client-2")

    with pytest.raises(RateLimitExceeded) as exc_info:
        limiter.check("client-2")

    assert exc_info.value.http_status == 429
    assert "Retry-After" in exc_info.value.headers


def test_webhook_body_size_limit_rejection(api_client):
    large_headers = {
        "Content-Length": "100000",
        "X-Razorpay-Signature": "invalid",
    }
    response = api_client.post("/api/gateway/razorpay/webhooks", headers=large_headers)
    assert response.status_code == 401  # GatewaySignatureInvalid mapped status
