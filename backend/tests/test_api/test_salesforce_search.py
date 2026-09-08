"""Salesforce Search/Get Record full-stack tests (Phase 8).

Proves the complete operation flow through the real stack (API -> queue
-> worker -> engine -> connector -> provider client) with a mocked
SafeHTTPClient:

1. Validate input          (connector op layer)
2. Resolve credentials     (CredentialResolver via the engine)
3. Call Salesforce Provider Client
4. Receive Salesforce response
5. Normalize the response
6. Return result to the workflow execution
7. Persist the execution result
8. Never expose credentials

Scenarios: success, invalid input, authentication failure, API failure,
timeout. No live Salesforce call is made.
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

LEAD_RECORD = {"Id": "00Qabc123", "Name": "Jane Doe", "Email": "jane@example.com", "Company": "Acme"}


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
    """Connector-only node types need the registry populated (tests don't
    run the lifespan, so register explicitly)."""
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


def _search_workflow(credential_id: str, workflow_id: str, search_value: str = "{{ $json.email }}") -> dict:
    return {
        "id": workflow_id,
        "name": "SF Search Lead",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "sf",
                "type": "salesforce",
                "parameters": {
                    "operation": "search",
                    "object_name": "Lead",
                    "search_field": "Email",
                    "search_value": search_value,
                },
                "settings": {},
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


def test_search_success_full_stack(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sf_search_ok"
    client.post("/api/workflows", json=_search_workflow(meta["id"], wf_id), headers=headers)

    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": LEAD_RECORD["Id"]}]}),
        _json_response(200, LEAD_RECORD),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data={"email": "jane@example.com"})
    finally:
        patcher.stop()

    # Step 3-5: the provider was called with the resolved credential.
    token_call = next(c for c in fake.calls if "/services/oauth2/token" in c[1])
    assert "client_secret=S3CR3T_CLIENT_SECRET_ZZZ" in token_call[2]["data"]
    search_call = fake.calls[1]
    assert search_call[1] == "https://myorg.salesforce.com/services/data/v63.0/query"
    assert search_call[2]["params"]["q"] == "SELECT Id FROM Lead WHERE Email = 'jane@example.com' LIMIT 1"
    assert search_call[2]["headers"]["Authorization"] == "Bearer tok123"

    # Step 6: the normalized result reached the workflow output.
    assert data["status"] == "success"
    assert data["node_statuses"]["sf"] == "success"
    output = data["results"]["outputs"]["sf"]["main"][0]
    assert output["found"] is True
    assert output["record"]["Id"] == LEAD_RECORD["Id"]
    assert output["record"]["Email"] == "jane@example.com"
    assert output["object_name"] == "Lead"
    assert output["search_field"] == "Email"

    # Step 7: the execution result is persisted and re-fetchable.
    detail = client.get(f"/api/executions/{execution_id}", headers=headers).json()
    assert detail["data"]["results"]["outputs"]["sf"]["main"][0]["found"] is True
    items = client.get(f"/api/executions/{execution_id}/items", headers=headers).json()
    sf_items = [i for i in items["data"] if i["node_id"] == "sf"]
    assert sf_items and sf_items[0]["outputs"]["main"][0]["found"] is True

    # Step 8: no credentials anywhere in the responses.
    _assert_no_secrets(data, "execution detail")
    _assert_no_secrets(items, "execution items")
    trace = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()
    _assert_no_secrets(trace, "execution trace")


def test_search_not_found_full_stack(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sf_search_miss"
    client.post("/api/workflows", json=_search_workflow(meta["id"], wf_id), headers=headers)

    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data={"email": "nobody@example.com"})
    finally:
        patcher.stop()

    assert data["status"] == "success"
    output = data["results"]["outputs"]["sf"]["main"][0]
    assert output["found"] is False
    assert output["record"] is None
    assert len(fake.calls) == 2  # no record fetch for a miss


# ----------------------------------------------------------------------
# Invalid input (full stack)
# ----------------------------------------------------------------------


def test_search_invalid_input_fails_run(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sf_search_invalid"
    client.post("/api/workflows", json=_search_workflow(meta["id"], wf_id, search_value=""), headers=headers)

    patcher, fake = _patch_client([])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data={"email": "jane@example.com"})
    finally:
        patcher.stop()

    assert data["status"] == "failed"
    assert data["error"]["code"] == "CONNECTOR_BAD_REQUEST"
    assert data["error"]["node_id"] == "sf"
    assert data["error"]["retryable"] is False
    assert "search value" in data["error"]["message"]
    assert fake.calls == []  # validated before any network call
    _assert_no_secrets(data, "execution detail for invalid input")


# ----------------------------------------------------------------------
# Authentication failure (full stack)
# ----------------------------------------------------------------------


def test_search_auth_failure_fails_run(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sf_search_auth"
    client.post("/api/workflows", json=_search_workflow(meta["id"], wf_id), headers=headers)

    patcher, _fake = _patch_client([
        httpx.Response(401, json=[{"message": "invalid_grant"}], request=httpx.Request("GET", "http://fake")),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data={"email": "jane@example.com"})
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


def test_search_api_failure_fails_run(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sf_search_api"
    client.post("/api/workflows", json=_search_workflow(meta["id"], wf_id), headers=headers)

    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(500, json=[{"message": "Internal Server Error"}], request=httpx.Request("GET", "http://fake")),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data={"email": "jane@example.com"})
    finally:
        patcher.stop()

    assert data["status"] == "failed"
    assert data["error"]["code"] == "CONNECTOR_UNAVAILABLE"
    assert data["error"]["node_id"] == "sf"
    assert data["error"]["retryable"] is True
    _assert_no_secrets(data, "execution detail for api failure")


# ----------------------------------------------------------------------
# Timeout (full stack)
# ----------------------------------------------------------------------


def test_search_timeout_fails_run(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sf_search_timeout"
    client.post("/api/workflows", json=_search_workflow(meta["id"], wf_id), headers=headers)

    patcher, _fake = _patch_client([_json_response(200, TOKEN_BODY)], client_cls=RaisingFakeHTTPClient)
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data={"email": "jane@example.com"})
    finally:
        patcher.stop()

    assert data["status"] == "failed"
    assert data["error"]["code"] == "CONNECTOR_TIMEOUT"
    assert data["error"]["node_id"] == "sf"
    assert data["error"]["retryable"] is True
    _assert_no_secrets(data, "execution detail for timeout")