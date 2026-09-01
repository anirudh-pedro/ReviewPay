"""Minimal replaceable authentication and scope boundary for operational APIs."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
from typing import Annotated

from fastapi import Depends, Header

from app.core.config import Settings
from app.core.errors import RevivePayError
from app.api.deps import SettingsDep


@dataclass(frozen=True)
class Principal:
    subject: str
    scopes: frozenset[str]
    authenticated: bool


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


def get_principal(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Resolve a principal without embedding credentials in routes or services."""
    if settings.auth_mode == "disabled":
        return Principal(subject="local-demo", scopes=frozenset({"*"}), authenticated=False)

    prefix = "Bearer "
    token = authorization[len(prefix):] if authorization and authorization.startswith(prefix) else ""
    if not settings.api_key or not token or not hmac.compare_digest(token, settings.api_key):
        raise AuthenticationRequired()
    return Principal(subject="api-key", scopes=settings.auth_scopes, authenticated=True)


def require_operations(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    if "*" not in principal.scopes and "operations:write" not in principal.scopes:
        raise AuthorizationDenied("operations:write")
    return principal


def require_demo_reset(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    if "*" not in principal.scopes and "demo:reset" not in principal.scopes:
        raise AuthorizationDenied("demo:reset")
    return principal


OperationsPrincipalDep = Annotated[Principal, Depends(require_operations)]
DemoResetPrincipalDep = Annotated[Principal, Depends(require_demo_reset)]
