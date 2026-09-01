"""Phase 4 API safety and authorization contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_settings_fail_closed_without_api_key_and_queue_mode():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", auth_mode="disabled")


def test_security_headers_and_correlation_id_are_returned(api_client):
    response = api_client.get("/health", headers={"X-Request-ID": "operator-run_01"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "operator-run_01"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "internal" not in response.text.lower()


def test_operational_endpoint_rejects_missing_or_invalid_bearer(api_client, settings, api_prefix):
    from app.api.deps import settings_dep

    secured = Settings(
        _env_file=None,
        **{**settings.model_dump(), "auth_mode": "api_key", "api_key": "phase4-test-key"},
    )
    api_client.app.dependency_overrides[settings_dep] = lambda: secured

    missing = api_client.post(f"{api_prefix}/recovery/autopilot", json={})
    invalid = api_client.post(f"{api_prefix}/recovery/autopilot", json={}, headers={"Authorization": "Bearer wrong"})

    assert missing.status_code == invalid.status_code == 401
    assert missing.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert missing.headers["WWW-Authenticate"] == "Bearer"


def test_authorized_operations_continue_to_work(api_client, settings, api_prefix):
    from app.api.deps import settings_dep

    secured = Settings(
        _env_file=None,
        **{**settings.model_dump(), "auth_mode": "api_key", "api_key": "phase4-test-key"},
    )
    api_client.app.dependency_overrides[settings_dep] = lambda: secured
    response = api_client.post(
        f"{api_prefix}/demo/reset",
        json={"background_customers": 1},
        headers={"Authorization": "Bearer phase4-test-key"},
    )
    assert response.status_code == 200


def test_cors_preflight_and_error_responses_carry_security_and_correlation_headers(api_client, api_prefix):
    preflight = api_client.options(
        f"{api_prefix}/payments",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"

    invalid = api_client.get(f"{api_prefix}/payments?limit=101", headers={"X-Request-ID": "invalid-page-01"})
    assert invalid.status_code == 422
    assert invalid.headers["X-Request-ID"] == "invalid-page-01"
    assert invalid.headers["X-Content-Type-Options"] == "nosniff"
