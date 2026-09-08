
"""Phase 16: execution history for Salesforce retries (full stack).

Verifies the durable execution record: the trace note for a retried
update ("succeeded after 1 retries"), and the typed failure state
(never-retried create) with its retry budget recorded.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

pytestmark = pytest.mark.timing

from app.connectors import get_registry, register_builtin_connectors
from tests.test_api.conftest import auth_headers, register

SF_ID_15 = "00Qabcdefgh1234"
TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"

SF_DATA = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "cid_123",
    "client_secret": "S3CR3T_CLIENT_SECRET_ZZZ",
    "username": "user@example.com",
    "password": "P4SS_+_TOK3N_ZZZ",
    "api_version": "v63.0",
}

TOKEN_BODY = {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"}

RETRY_SETTINGS = {"retry_max_attempts": 2, "retry_backoff_seconds": 0.01}


class FakeHTTPClient:
    """Scripted SafeHTTPClient: token + data responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    @property
    def data_calls(self) -> list[Any]:
        return [c for c in self.calls if c[1] != TOKEN_URL]


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _token_response() -> httpx.Response:
    return _json_response(200, TOKEN_BODY)


def _sf_error(status: int, message: str = "API error") -> httpx.Response:
    return httpx.Response(
        status, json=[{"errorCode": "X", "message": message}],
        request=httpx.Request("GET", "http://fake"),
    )


def _patch_client(responses: list[httpx.Response]):
    fake = FakeHTTPClient(responses)
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


def _workflow_json(credential_id: str, workflow_id: str, operation: str, settings=None) -> dict:
    parameters: dict[str, Any] = {"operation": operation, "object_name": "Lead"}
    if operation == "update":
        parameters.update({"record_id": SF_ID_15, "record": {"Company": "Acme"}})
    elif operation == "create":
        parameters["record"] = {"Company": "Acme"}
    elif operation == "query":
        parameters = {"operation": "query", "soql": "SELECT Id FROM Lead"}
    return {
        "id": workflow_id,
        "name": "SF Retry History",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "sf", "type": "salesforce", "parameters": parameters,
             "settings": settings or {}, "credentials": {"salesforce": credential_id}},
        ],
        "connections": [{"source": "trigger", "target": "sf"}],
        "settings": {},
    }


def _run_and_poll(client, headers, wf_id):
    resp = client.post(f"/api/workflows/{wf_id}/run", json={}, headers=headers)
    assert resp.status_code == 202, resp.text
    execution_id = resp.json()["data"]["execution_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("running", "queued", "cancelling"):
            return execution_id, data
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish: {data['status']}")


def test_execution_history_records_retried_update(client):
    """Update retried once -> history shows the retry note."""
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)

    wf_id = "wf_sf_retry_ok"
    client.post("/api/workflows", json=_workflow_json(meta["id"], wf_id, "update", RETRY_SETTINGS), headers=headers)
    patcher, _fake = _patch_client([
        _token_response(),
        _sf_error(429, "API_REQUESTS_EXCEEDED"),
        _json_response(204, {}),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id)
    finally:
        patcher.stop()
    assert data["status"] == "success"
    trace = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()["data"]["steps"]
    sf_step = next(s for s in trace if s["node_id"] == "sf")
    assert sf_step["status"] == "success"
    assert "succeeded after 1 retries" in sf_step["note"]


def test_execution_history_records_failed_create_state(client):
    """Create never retries even with settings; the failure state is typed and persists."""
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)

    wf_id = "wf_sf_retry_noretry"
    client.post("/api/workflows", json=_workflow_json(meta["id"], wf_id, "create", RETRY_SETTINGS), headers=headers)
    patcher, fake = _patch_client([
        _token_response(),
        _sf_error(429, "API_REQUESTS_EXCEEDED"),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id)
    finally:
        patcher.stop()
    assert len(fake.data_calls) == 1  # no blind retry, even with settings
    assert data["status"] == "failed"
    assert data["error"]["code"] == "CONNECTOR_RATE_LIMITED"
    assert data["error"]["retryable"] is False
    trace = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()["data"]["steps"]
    sf_step = next(s for s in trace if s["node_id"] == "sf")
    assert sf_step["status"] == "error"
    assert sf_step["error"]["code"] == "CONNECTOR_RATE_LIMITED"