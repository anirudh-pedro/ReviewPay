"""Normalized environment-profile policy and its fail-closed boundaries.

Covers Requirements 3.4-3.5, 7.7, 9.1-9.9, 10.2, 10.4, 14.11, 17.5, 17.7.

Two invariants shape every test here:

- a protected profile (``staging``, ``production``) cannot start or accept an
  operational mutation without approved secret authentication and a scoped,
  authenticated principal;
- no response, header, or safe error envelope carries a credential, a
  configuration value, a connection string, or an internal exception detail.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect

from app.api.auth import (
    AuthenticationRequired,
    AuthorizationDenied,
    DEMO_RESET_SCOPE,
    OPERATIONS_SCOPE,
    Principal,
    authorize_scope,
    describe_authentication,
)
from app.core.config import (
    DEVELOPMENT_PROFILES,
    ENVIRONMENT_PROFILE_ALIASES,
    ENVIRONMENT_PROFILES,
    PROFILE_POLICIES,
    PROTECTED_PROFILES,
    RESETTABLE_PROFILES,
    Settings,
    resolve_environment_profile,
)
from app.db.init_db import SchemaBootstrapForbidden, create_all, drop_all, table_names
from app.main import StartupSecurityError, _apply_security_headers, _enforce_startup_security, create_app

PROTECTED_LABELS = ("staging", "production")


def _protected_settings(label: str, **overrides) -> Settings:
    """A minimally valid protected-profile configuration."""
    values = {
        "environment": label,
        "auth_mode": "api_key",
        "api_key": "profile-test-key",
        "execution_mode": "enqueue",
        "database_url": "sqlite:///:memory:",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


# ---------------------------------------------------------------------------
# Profile normalization (Requirement 9.1)
# ---------------------------------------------------------------------------


def test_every_supported_label_resolves_to_one_of_the_five_profiles():
    for label, profile in ENVIRONMENT_PROFILE_ALIASES.items():
        assert profile in ENVIRONMENT_PROFILES
        assert resolve_environment_profile(label.upper()) == profile


def test_the_existing_default_environment_resolves_to_the_local_profile():
    """The shipped default is ``development``; its behaviour must not change."""
    settings = Settings(_env_file=None)
    assert settings.environment == "development"
    assert settings.environment_profile == "local"
    assert settings.profile_policy.allows_disabled_authentication is True
    assert settings.is_production is False
    assert settings.is_protected_profile is False


def test_an_unrecognized_environment_label_is_rejected_rather_than_guessed():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="sandbox-ish")
    with pytest.raises(ValueError):
        resolve_environment_profile("sandbox-ish")


def test_profile_policy_matrix_is_complete_and_fails_closed():
    assert set(PROFILE_POLICIES) == set(ENVIRONMENT_PROFILES)
    for profile, policy in PROFILE_POLICIES.items():
        protected = profile in PROTECTED_PROFILES
        assert policy.allows_disabled_authentication is (profile in DEVELOPMENT_PROFILES)
        assert policy.requires_secret_authentication is protected
        assert policy.requires_authenticated_operational_principal is protected
        assert policy.allows_wildcard_cors_origins is not protected
        assert policy.requires_schema_revision_check is protected
        assert policy.requires_transport_security is protected
        assert policy.allows_destructive_reset is (profile in RESETTABLE_PROFILES)
        assert policy.allows_schema_bootstrap is not protected
        # Requirement 7.7: no profile enables a real-money provider executor.
        assert policy.allows_provider_action_executor is False


# ---------------------------------------------------------------------------
# Startup configuration gates (Requirement 9.3, 9.9, 17.7)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", PROTECTED_LABELS)
def test_protected_profiles_fail_closed_without_secret_authentication(label):
    with pytest.raises(ValidationError):
        _protected_settings(label, auth_mode="disabled")
    with pytest.raises(ValidationError):
        _protected_settings(label, api_key=None)
    with pytest.raises(ValidationError):
        _protected_settings(label, api_key_scopes="")


@pytest.mark.parametrize("label", PROTECTED_LABELS)
def test_protected_profiles_reject_wildcard_cors_origins(label):
    with pytest.raises(ValidationError):
        _protected_settings(label, backend_cors_origins="*")


def test_local_profile_still_accepts_disabled_auth_and_wildcard_origins():
    settings = Settings(_env_file=None, environment="local", backend_cors_origins="*")
    assert settings.auth_mode == "disabled"
    assert settings.cors_origins == ["*"]


def test_production_still_requires_enqueue_execution():
    with pytest.raises(ValidationError):
        _protected_settings("production", execution_mode="synchronous")
    # Staging keeps the existing synchronous default available.
    assert _protected_settings("staging", execution_mode="synchronous").execution_mode == "synchronous"


@pytest.mark.parametrize("label", PROTECTED_LABELS)
def test_startup_refuses_a_protected_profile_whose_security_config_was_removed(label):
    """Validation normally blocks this; the boundary gate must block it too."""
    settings = _protected_settings(label)
    settings.auth_mode = "disabled"
    with pytest.raises(StartupSecurityError):
        _enforce_startup_security(settings)

    settings = _protected_settings(label)
    settings.api_key = ""
    with pytest.raises(StartupSecurityError):
        _enforce_startup_security(settings)

    settings = _protected_settings(label)
    settings.api_key_scopes = ""
    with pytest.raises(StartupSecurityError):
        _enforce_startup_security(settings)

    settings = _protected_settings(label)
    settings.backend_cors_origins = "*"
    with pytest.raises(StartupSecurityError):
        _enforce_startup_security(settings)


def test_startup_security_error_names_no_configuration_value():
    settings = _protected_settings("production")
    settings.api_key = "super-secret-production-key"
    settings.auth_mode = "disabled"
    with pytest.raises(StartupSecurityError) as raised:
        _enforce_startup_security(settings)
    assert "super-secret-production-key" not in str(raised.value)


def test_development_profiles_start_without_security_configuration():
    for label in ("local", "development", "demo", "test"):
        _enforce_startup_security(Settings(_env_file=None, environment=label))


# ---------------------------------------------------------------------------
# Non-secret authentication status (Requirement 9.2, 9.7, 9.8)
# ---------------------------------------------------------------------------


def test_authentication_status_reports_the_mode_without_any_secret():
    settings = _protected_settings("production", api_key="do-not-leak-this-key")
    status = describe_authentication(settings)
    assert status.environment_profile == "production"
    assert status.authentication_mode == "api_key"
    assert status.authenticated_principal_required is True
    assert "do-not-leak-this-key" not in repr(status)


def test_profile_summary_excludes_secrets_and_the_database_url():
    settings = _protected_settings(
        "production",
        api_key="do-not-leak-this-key",
        database_url="postgresql+psycopg://user:hunter2@db:5432/revivepay",
        razorpay_enabled=True,
        razorpay_key_id="rzp_test_id",
        razorpay_key_secret="rzp_secret_value",
    )
    rendered = " ".join(f"{key}={value}" for key, value in settings.profile_summary().items())
    for secret in ("do-not-leak-this-key", "hunter2", "rzp_secret_value", "postgresql"):
        assert secret not in rendered
    assert "environment_profile=production" in rendered
    assert "authentication_mode=api_key" in rendered


def test_health_reports_the_profile_and_mode_without_secrets(api_client):
    body = api_client.get("/health").json()
    assert body["environment"] == "development"
    assert body["environment_profile"] == "local"
    assert body["authentication_mode"] == "disabled"
    assert body["authenticated_principal_required"] is False
    # Existing fields remain (Requirement 3.4).
    assert {"status", "app_name", "version", "environment", "virtual_clock_time", "data_source"} <= set(body)


def test_readyz_keeps_its_existing_keys_and_adds_profile_evidence(api_client):
    body = api_client.get("/readyz").json()
    assert body["status"] == "ready"
    assert body["database"] == "reachable"
    assert body["environment_profile"] == "local"
    assert body["authentication_mode"] == "disabled"


# ---------------------------------------------------------------------------
# Scoped principals for operational mutations (Requirement 9.3, 9.4, 9.5)
# ---------------------------------------------------------------------------


def test_development_principal_cannot_satisfy_a_scope_in_a_protected_profile():
    development = Principal(subject="local-demo", scopes=frozenset({"*"}), authenticated=False)
    assert authorize_scope(development, Settings(_env_file=None), OPERATIONS_SCOPE) is development
    with pytest.raises(AuthenticationRequired):
        authorize_scope(development, _protected_settings("production"), OPERATIONS_SCOPE)


def test_authenticated_principal_still_needs_the_operation_scope():
    settings = _protected_settings("production", api_key_scopes="demo:reset")
    principal = Principal(subject="api-key", scopes=settings.auth_scopes, authenticated=True)
    with pytest.raises(AuthorizationDenied) as raised:
        authorize_scope(principal, settings, OPERATIONS_SCOPE)
    assert OPERATIONS_SCOPE in str(raised.value)
    assert authorize_scope(principal, settings, DEMO_RESET_SCOPE) is principal


def test_disabled_auth_in_a_protected_profile_returns_a_safe_service_error(api_client, api_prefix):
    from app.api.deps import settings_dep

    misconfigured = _protected_settings("staging")
    misconfigured.auth_mode = "disabled"
    api_client.app.dependency_overrides[settings_dep] = lambda: misconfigured

    response = api_client.post(f"{api_prefix}/recovery/autopilot", json={})
    assert response.status_code == 503
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == "SECURITY_CONFIGURATION_INVALID"
    assert "profile-test-key" not in response.text
    assert "sqlite" not in response.text.lower()


def test_protected_profile_requires_a_bearer_credential_for_mutations(api_client, api_prefix, settings):
    from app.api.deps import settings_dep

    staging = _protected_settings(
        "staging",
        virtual_clock_state_path=settings.virtual_clock_state_path,
        simulation_seed=settings.simulation_seed,
        virtual_clock_start=settings.virtual_clock_start,
    )
    api_client.app.dependency_overrides[settings_dep] = lambda: staging

    unauthenticated = api_client.post(f"{api_prefix}/recovery/autopilot", json={})
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    authorized = api_client.post(
        f"{api_prefix}/recovery/autopilot",
        json={},
        headers={"Authorization": "Bearer profile-test-key"},
    )
    assert authorized.status_code == 200


def test_reset_is_gated_to_resettable_profiles(api_client, api_prefix, settings):
    from app.api.deps import settings_dep

    staging = _protected_settings("staging", virtual_clock_state_path=settings.virtual_clock_state_path)
    api_client.app.dependency_overrides[settings_dep] = lambda: staging

    response = api_client.post(
        f"{api_prefix}/demo/reset",
        json={},
        headers={"Authorization": "Bearer profile-test-key"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "DEMO_RESET_FORBIDDEN"
    assert "staging" in response.json()["error"]["message"]


# ---------------------------------------------------------------------------
# Schema bootstrap boundary (Requirement 10.2, 10.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", PROTECTED_LABELS)
def test_schema_bootstrap_is_refused_in_protected_profiles(label, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / f'{label}.db'}")
    protected = _protected_settings(label)
    try:
        with pytest.raises(SchemaBootstrapForbidden):
            create_all(engine, settings=protected)
        with pytest.raises(SchemaBootstrapForbidden):
            drop_all(engine, settings=protected)
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


def test_documented_development_bootstrap_still_works(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'local.db'}")
    local = Settings(_env_file=None, environment="development")
    try:
        create_all(engine, settings=local)
        assert "recovery_cases" in table_names(engine)
        drop_all(engine, settings=local)
        assert table_names(engine) == []
    finally:
        engine.dispose()


def test_schema_bootstrap_error_is_a_safe_envelope_without_configuration_detail():
    error = SchemaBootstrapForbidden("create_all", "production")
    assert error.code == "SCHEMA_BOOTSTRAP_FORBIDDEN"
    assert "Alembic" in error.message
    assert "sqlite" not in error.message.lower()


# ---------------------------------------------------------------------------
# Retained cross-cutting HTTP safeguards (Requirement 9.6, 3.4)
# ---------------------------------------------------------------------------


class _HeaderProbe:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


def test_transport_security_header_is_added_only_where_the_profile_requires_it():
    baseline = _HeaderProbe()
    _apply_security_headers(baseline, transport_security=False)
    assert "Strict-Transport-Security" not in baseline.headers
    assert baseline.headers["X-Content-Type-Options"] == "nosniff"

    protected = _HeaderProbe()
    _apply_security_headers(protected, transport_security=True)
    assert protected.headers["Strict-Transport-Security"].startswith("max-age=")


def test_staging_application_serves_security_headers_and_bounded_requests(monkeypatch, tmp_path):
    from app.api.deps import settings_dep

    staging = _protected_settings(
        "staging",
        virtual_clock_state_path=str(tmp_path / "clock.json"),
        max_request_body_bytes=64,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: staging)
    app = create_app()
    app.dependency_overrides[settings_dep] = lambda: staging

    with TestClient(app, raise_server_exceptions=False) as client:
        health = client.get("/health", headers={"X-Request-ID": "staging-probe_01"})
        assert health.status_code == 200
        assert health.headers["X-Request-ID"] == "staging-probe_01"
        assert health.headers["Strict-Transport-Security"].startswith("max-age=")
        assert health.json()["environment_profile"] == "staging"
        assert "profile-test-key" not in health.text

        oversized = client.post("/api/payments/simulate", content=b"x" * 512, headers={"Content-Type": "application/json"})
        assert oversized.status_code == 413
        body = oversized.json()
        assert set(body) == {"error"}
        assert body["error"]["code"] == "PAYLOAD_TOO_LARGE"

    app.dependency_overrides.clear()
