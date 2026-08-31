"""Application factory, middleware, and error handling tests.

Requirement 1.1, 1.7, 1.8, 24.1, 24.5.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.enums import CaseState
from app.core.errors import CaseAlreadyTerminal, RecordNotFound
from app.main import RESPONSE_TIME_HEADER, create_app


class ProbeBody(BaseModel):
    """Declared at module level: this file uses postponed annotations, so a model
    defined inside a test function would not be resolvable by FastAPI."""

    quantity: int


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def test_create_app_returns_a_configured_application():
    """Requirement 1.1."""
    app = create_app()
    settings = get_settings()
    assert app.title == settings.app_name
    assert app.version == settings.version


def test_health_endpoint_reports_metadata_and_simulation_time(client):
    """Requirement 24.1."""
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    settings = get_settings()
    assert body["status"] == "ok"
    assert body["app_name"] == settings.app_name
    assert body["version"] == settings.version
    assert body["environment"] == settings.environment
    assert "virtual_clock_time" in body


def test_health_is_served_outside_the_api_prefix(client):
    """Requirement 24.5."""
    prefix = get_settings().api_prefix
    assert client.get("/health").status_code == 200
    assert client.get(f"{prefix}/health").status_code == 404


def test_response_time_header_is_present(client):
    """Requirement 1.7."""
    response = client.get("/health")
    assert RESPONSE_TIME_HEADER in response.headers
    assert float(response.headers[RESPONSE_TIME_HEADER]) >= 0.0


def test_openapi_and_docs_render(client):
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_domain_error_is_returned_in_the_standard_envelope():
    """Requirement 1.8: RecordNotFound maps to 404."""
    app = create_app()
    probe = APIRouter()

    @probe.get("/_probe/not-found")
    def _raise_not_found():
        raise RecordNotFound("RecoveryCase", "case_missing")

    app.include_router(probe)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/_probe/not-found")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "case_missing" in body["error"]["message"]
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}


def test_terminal_case_error_maps_to_conflict():
    """Requirement 24.9."""
    app = create_app()
    probe = APIRouter()

    @probe.post("/_probe/terminal")
    def _raise_terminal():
        raise CaseAlreadyTerminal("case_0001", CaseState.RECOVERED)

    app.include_router(probe)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/_probe/terminal")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CASE_TERMINAL"
    assert "RECOVERED" in body["error"]["message"]


def test_validation_error_names_the_offending_field():
    """Requirement 3.6."""
    app = create_app()
    probe = APIRouter()

    @probe.post("/_probe/validate")
    def _validate(payload: ProbeBody):
        return {"quantity": payload.quantity}

    app.include_router(probe)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/_probe/validate", json={"quantity": "not-a-number"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "quantity" in body["error"]["message"]


def test_unhandled_error_is_masked_as_internal_error():
    app = create_app()
    probe = APIRouter()

    @probe.get("/_probe/boom")
    def _boom():
        raise RuntimeError("internal detail that must not leak")

    app.include_router(probe)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/_probe/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "internal detail" not in body["error"]["message"]
