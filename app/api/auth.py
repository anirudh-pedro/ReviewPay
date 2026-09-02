"""Minimal replaceable authentication and scope boundary for operational APIs."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
from typing import Annotated, Callable

from fastapi import Depends, Header

from app.core.config import Settings
from app.core.errors import RevivePayError
from app.api.deps import SettingsDep

#: Scope granting the operational mutations that drive recovery work.
OPERATIONS_SCOPE = "operations:write"
#: Dedicated scope for the destructive demo reset (Requirement 9.5).
DEMO_RESET_SCOPE = "demo:reset"
#: The disabled-authentication development principal holds every scope.
WILDCARD_SCOPE = "*"
#: Subject reported for the documented local/demo/test development principal.
DEVELOPMENT_SUBJECT = "local-demo"


@dataclass(frozen=True)
class Principal:
    subject: str
    scopes: frozenset[str]
    authenticated: bool


@dataclass(frozen=True)
class AuthenticationStatus:
    """Non-secret authentication evidence for operational status responses.

    Carries the *mode* and the profile requirement only. It never carries the API
    key, a scope secret, or any configuration value (Requirement 9.2, 9.7).
    """

    environment_profile: str
    authentication_mode: str
    authenticated_principal_required: bool


class AuthenticationRequired(RevivePayError):
    code = "AUTHENTICATION_REQUIRED"
    http_status = 401
    headers = {"WWW-Authenticate": "Bearer"}

    def __init__(self) -> None:
        super().__init__("Authentication is required for this operation.")


class AuthorizationDenied(RevivePayError):
    code = "AUTHORIZATION_DENIED"
    http_status = 403

    def __init__(self, scope: str) -> None:
        super().__init__(f"The authenticated principal lacks required scope '{scope}'.")


class SecurityConfigurationInvalid(RevivePayError):
    """A protected profile is running without the security configuration it requires.

    Startup validation normally prevents this. The gate is repeated here so an
    injected or reloaded configuration cannot open an unauthenticated mutation
    path. The message names no configuration value (Requirement 9.7).
    """

    code = "SECURITY_CONFIGURATION_INVALID"
    http_status = 503

    def __init__(self) -> None:
        super().__init__("This deployment is not accepting operational requests until required security configuration is present.")


def describe_authentication(settings: Settings) -> AuthenticationStatus:
    """Report the active authentication mode without exposing any secret."""
    policy = settings.profile_policy
    return AuthenticationStatus(
        environment_profile=policy.profile,
        authentication_mode=settings.auth_mode,
        authenticated_principal_required=policy.requires_authenticated_operational_principal,
    )


def get_principal(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Resolve a principal without embedding credentials in routes or services."""
    if settings.auth_mode == "disabled":
        if not settings.profile_policy.allows_disabled_authentication:
            raise SecurityConfigurationInvalid()
        return Principal(subject=DEVELOPMENT_SUBJECT, scopes=frozenset({WILDCARD_SCOPE}), authenticated=False)

    prefix = "Bearer "
    token = authorization[len(prefix):] if authorization and authorization.startswith(prefix) else ""
    if not settings.api_key or not token or not hmac.compare_digest(token, settings.api_key):
        raise AuthenticationRequired()
    return Principal(subject="api-key", scopes=settings.auth_scopes, authenticated=True)


def authorize_scope(principal: Principal, settings: Settings, scope: str) -> Principal:
    """Enforce the profile's principal requirement and then the operation scope.

    Staging and production require an authenticated principal for every
    Operational Mutation, so the development principal cannot satisfy a scope
    there even though it holds the wildcard (Requirement 9.3, 9.4).
    """
    if settings.profile_policy.requires_authenticated_operational_principal and not principal.authenticated:
        raise AuthenticationRequired()
    if WILDCARD_SCOPE not in principal.scopes and scope not in principal.scopes:
        raise AuthorizationDenied(scope)
    return principal


def require_scope(scope: str) -> Callable[[Settings, Principal], Principal]:
    """Build a least-privilege dependency for one operation scope."""

    def _dependency(
        settings: SettingsDep,
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> Principal:
        return authorize_scope(principal, settings, scope)

    return _dependency


def require_operations(
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    return authorize_scope(principal, settings, OPERATIONS_SCOPE)


def require_demo_reset(
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    return authorize_scope(principal, settings, DEMO_RESET_SCOPE)


OperationsPrincipalDep = Annotated[Principal, Depends(require_operations)]
DemoResetPrincipalDep = Annotated[Principal, Depends(require_demo_reset)]
