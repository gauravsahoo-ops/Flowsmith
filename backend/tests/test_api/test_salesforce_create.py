"""Salesforce Create Record full-stack tests (Phase 9).

Proves the complete create flow through the real stack (API -> queue ->
worker -> engine -> connector -> provider client) with a mocked
SafeHTTPClient:

- input validation
- credential resolution
- Salesforce API call
- normalized response
- execution persistence
- error handling
- retry classification (create is never auto-retried — no duplicates)
- idempotency consideration (create declared non_idempotent)

Scenarios: success (Lead with template values), invalid input,
authentication failure, API failure, timeout, and no duplicate retry.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

pytestmark = pytest.mark.timing

from app.connectors import get_registry, register_builtin_connectors
from tests.test_api.conftest import auth_headers, register

SF_DATA = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "cid_123",
    "client_secret": "S3CR3T_CLIENT_SECRET_ZZZ",
    "username": "user@example.com",
    "password": "P4SS_+_TOK3N_ZZZ",
    "api_version": "v63.0",
}

SECRET_MARKERS = ["S3CR3T_CLIENT_SECRET_ZZZ", "P4SS_+_TOK3N_ZZZ", "cid_123"]

TOKEN_BODY = {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"}

LEAD = {
    "first_name": "Automation",
    "last_name": "Test",
    "company": "Test Company",
    "email": "test@example.com",
}

LEAD_RESOLVED = {
    "FirstName": "Automation",
    "LastName": "Test",
    "Company": "Test Company",
    "Email": "test@example.com",
}


class FakeSFHTTPClient:
    """Scripted SafeHTTPClient replacement: token + data API responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(self, method, url, **kwargs) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class RaisingFakeHTTPClient(FakeSFHTTPClient):
    """Scripted client that raises for the final response (timeout test)."""

    async def request(self, method, url, **kwargs) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        if len(self.calls) >= 2:
            raise httpx.TimeoutException("request timed out")
        return self.responses.pop(0)


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _patch_client(responses: list[httpx.Response], client_cls=FakeSFHTTPClient):
    fake = client_cls(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.providers.salesforce.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher, fake


@pytest.fixture(autouse=True)
def _connectors_registered():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    yield


def _setup(client):
    return auth_headers(register(client)["token"])


def _create_sf_credential(client, headers):
    resp = client.post("/api/credentials", json={"name": "SF Prod", "type": "salesforce", "data": SF_DATA}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _create_workflow(credential_id: str, workflow_id: str, record=None, settings=None) -> dict:
    return {
        "id": workflow_id,
        "name": "SF Create Lead",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "sf",
                "type": "salesforce",
                "parameters": {
                    "operation": "create",
                    "object_name": "Lead",
                    "record": record if record is not None else {
                        "FirstName": "{{ $json.first_name }}",
                        "LastName": "{{ $json.last_name }}",
                        "Company": "{{ $json.company }}",
                        "Email": "{{ $json.email }}",
                    },
                },
                "settings": settings or {},
                "credentials": {"salesforce": credential_id},
            },
        ],
        "connections": [{"source": "trigger", "target": "sf"}],
        "settings": {},
    }


def _run_and_poll(client, headers, wf_id, input_data=None):
    body = {"data": input_data} if input_data is not None else {}
    resp = client.post(f"/api/workflows/{wf_id}/run", json=body, headers=headers)
    assert resp.status_code == 202, resp.text
    execution_id = resp.json()["data"]["execution_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("running", "queued", "cancelling"):
            return execution_id, data
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish: {data['status']}")


def _assert_no_secrets(value: Any, where: str) -> None:
    text = json.dumps(value, default=str)
    for marker in SECRET_MARKERS:
        assert marker not in text, f"secret {marker!r} leaked into {where}"


# ----------------------------------------------------------------------
# Success (full stack)
# ----------------------------------------------------------------------


def test_create_success_full_stack(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sf_create_ok"
    client.post("/api/workflows", json=_create_workflow(meta["id"], wf_id), headers=headers)

    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(201, {"id": "00Qnew123", "success": True}),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data=LEAD)
    finally:
        patcher.stop()

    # Credential resolution: the token request carried the decrypted secrets.
    token_call = next(c for c in fake.calls if "/services/oauth2/token" in c[1])
    assert "client_secret=S3CR3T_CLIENT_SECRET_ZZZ" in token_call[2]["data"]

    # Salesforce API call: template values resolved into the record body.
    create_call = fake.calls[1]
    assert create_call[0] == "POST"
    assert create_call[1] == "https://myorg.salesforce.com/services/data/v63.0/sobjects/Lead"
    assert create_call[2]["json"] == LEAD_RESOLVED
    assert create_call[2]["headers"]["Authorization"] == "Bearer tok123"

    # Normalized response returned to the workflow execution.
    assert data["status"] == "success"
    assert data["node_statuses"]["sf"] == "success"
    output = data["results"]["outputs"]["sf"]["main"][0]
    assert output["id"] == "00Qnew123"
    assert output["success"] is True

    # Execution persistence: re-fetchable via detail and items.
    detail = client.get(f"/api/executions/{execution_id}", headers=headers).json()
    assert detail["data"]["results"]["outputs"]["sf"]["main"][0]["id"] == "00Qnew123"
    items = client.get(f"/api/executions/{execution_id}/items", headers=headers).json()
    sf_items = [i for i in items["data"] if i["node_id"] == "sf"]
    assert sf_items and sf_items[0]["outputs"]["main"][0]["id"] == "00Qnew123"

    # No credentials anywhere.
    _assert_no_secrets(data, "execution detail")
    _assert_no_secrets(items, "execution items")
    trace = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()
    _assert_no_secrets(trace, "execution trace")


# ----------------------------------------------------------------------
# Invalid input (full stack)
# ----------------------------------------------------------------------


def test_create_invalid_input_fails_run(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sf_create_invalid"
    client.post("/api/workflows", json=_create_workflow(meta["id"], wf_id, record={}), headers=headers)

    patcher, fake = _patch_client([])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data=LEAD)
    finally:
        patcher.stop()

    assert data["status"] == "failed"
    assert data["error"]["code"] == "CONNECTOR_BAD_REQUEST"
    assert data["error"]["node_id"] == "sf"
    assert data["error"]["retryable"] is False
    assert "record object" in data["error"]["message"]
    assert fake.calls == []  # validated before any network call
    _assert_no_secrets(data, "execution detail for invalid input")


# ----------------------------------------------------------------------
# Authentication failure (full stack)
# ----------------------------------------------------------------------


def test_create_auth_failure_fails_run(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sf_create_auth"
    client.post("/api/workflows", json=_create_workflow(meta["id"], wf_id), headers=headers)

    patcher, _fake = _patch_client([
        httpx.Response(401, json=[{"message": "invalid_grant"}], request=httpx.Request("GET", "http://fake")),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data=LEAD)
    finally:
        patcher.stop()

    assert data["status"] == "failed"
    assert data["error"]["code"] == "CONNECTOR_AUTH_FAILED"
    assert data["error"]["node_id"] == "sf"
    assert data["error"]["retryable"] is False
    _assert_no_secrets(data, "execution detail for auth failure")


# ----------------------------------------------------------------------
# API failure (full stack)
# ----------------------------------------------------------------------


def test_create_api_failure_fails_run(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sf_create_api"
    client.post("/api/workflows", json=_create_workflow(meta["id"], wf_id), headers=headers)

    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(400, json=[{"message": "INVALID_FIELD_FOR_INSERT_UPDATE: Email"}], request=httpx.Request("GET", "http://fake")),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data=LEAD)
    finally:
        patcher.stop()

    assert data["status"] == "failed"
    assert data["error"]["code"] == "CONNECTOR_BAD_REQUEST"
    assert data["error"]["node_id"] == "sf"
    assert data["error"]["retryable"] is False
    assert "INVALID_FIELD_FOR_INSERT_UPDATE" in data["error"]["message"]
    _assert_no_secrets(data, "execution detail for api failure")


# ----------------------------------------------------------------------
# Timeout (full stack)
# ----------------------------------------------------------------------


def test_create_timeout_fails_run(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sf_create_timeout"
    client.post("/api/workflows", json=_create_workflow(meta["id"], wf_id), headers=headers)

    patcher, _fake = _patch_client([_json_response(200, TOKEN_BODY)], client_cls=RaisingFakeHTTPClient)
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data=LEAD)
    finally:
        patcher.stop()

    assert data["status"] == "failed"
    assert data["error"]["code"] == "CONNECTOR_TIMEOUT"
    assert data["error"]["node_id"] == "sf"
    assert data["error"]["retryable"] is False  # create is never auto-retried
    _assert_no_secrets(data, "execution detail for timeout")


# ----------------------------------------------------------------------
# No duplicate retries (full stack)
# ----------------------------------------------------------------------


def test_create_never_auto_retries(client):
    """Even with retry settings, a 429 on create runs exactly once."""
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sf_create_noretry"
    settings = {"retry_max_attempts": 3, "retry_backoff_seconds": 0.01}
    client.post("/api/workflows", json=_create_workflow(meta["id"], wf_id, settings=settings), headers=headers)

    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(429, json=[{"message": "API_REQUESTS_EXCEEDED"}], request=httpx.Request("GET", "http://fake")),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data=LEAD)
    finally:
        patcher.stop()

    assert data["status"] == "failed"
    assert data["error"]["code"] == "CONNECTOR_RATE_LIMITED"
    assert data["error"]["node_id"] == "sf"
    assert data["error"]["retryable"] is False
    assert len(fake.calls) == 2  # token + exactly one create attempt
    _assert_no_secrets(data, "execution detail for no-retry run")