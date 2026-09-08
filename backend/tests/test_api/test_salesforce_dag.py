"""Phase 11: Salesforce inside a full DAG, through the real worker stack.

DAG under test:

    Manual Trigger -> Set Data -> Salesforce Search -> Set Data

Proves, end to end through the API -> queue -> worker -> engine path
(generic DAG execution, no special Salesforce path):

- data mapping (set_data output feeds the Salesforce search input)
- node output (Salesforce search result reaches the execution result)
- next-node input (final set_data consumes the Salesforce node output)
- worker execution (202 accepted, queued, executed, settled)
- execution persistence (detail / items / trace re-fetchable)
- execution history (GET /api/executions?workflow_id=...)
- retry (429 on search retried with retry settings, then success)
- timeout (transport timeout -> CONNECTOR_TIMEOUT, retryable)
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

INPUT = {"email": "jane@example.com"}

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
    """Scripted client that raises for the data API call (timeout test)."""

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


def _dag_workflow(credential_id: str, workflow_id: str, sf_settings=None) -> dict:
    return {
        "id": workflow_id,
        "name": "SF Lead Pipeline",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "sd1", "type": "set_data", "parameters": {"fields": {"email": "{{ $json.email }}"}}},
            {
                "id": "sf",
                "type": "salesforce",
                "parameters": {
                    "operation": "search",
                    "object_name": "Lead",
                    "search_field": "Email",
                    "search_value": "{{ $node.sd1.json.email }}",
                },
                "settings": sf_settings or {},
                "credentials": {"salesforce": credential_id},
            },
            {
                "id": "sd2",
                "type": "set_data",
                "parameters": {
                    "fields": {
                        "lead_email": "{{ $node.sf.json.record.Email }}",
                        "lead_name": "{{ $node.sf.json.record.Name }}",
                        "found": "{{ $node.sf.json.found }}",
                    }
                },
            },
        ],
        "connections": [
            {"source": "trigger", "target": "sd1"},
            {"source": "sd1", "target": "sf"},
            {"source": "sf", "target": "sd2"},
        ],
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


def _search_responses():
    return [
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qabc123"}]}),
        _json_response(200, LEAD_RECORD),
    ]


# ----------------------------------------------------------------------
# Success: the full DAG through the worker
# ----------------------------------------------------------------------


def test_dag_success_through_worker(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_dag_sf_ok"
    client.post("/api/workflows", json=_dag_workflow(meta["id"], wf_id), headers=headers)

    patcher, fake = _patch_client(_search_responses())
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data=INPUT)
    finally:
        patcher.stop()

    # Worker execution: the whole DAG settled as success.
    assert data["status"] == "success"
    assert data["node_statuses"] == {
        "trigger": "success", "sd1": "success", "sf": "success", "sd2": "success",
    }

    # Data mapping: set_data output fed the Salesforce search input.
    query_call = next(c for c in fake.calls if "/query" in c[1])
    assert query_call[2]["params"]["q"] == "SELECT Id FROM Lead WHERE Email = 'jane@example.com' LIMIT 1"

    # Node output: Salesforce search result in the execution result.
    sf_output = data["results"]["outputs"]["sf"]["main"][0]
    assert sf_output["found"] is True
    assert sf_output["record"]["Email"] == "jane@example.com"

    # Next-node input: the final set_data consumed the Salesforce output.
    assert data["results"]["outputs"]["sd2"]["main"][0] == {
        **sf_output,
        "lead_email": "jane@example.com",
        "lead_name": "Jane Doe",
    }

    # Execution persistence: detail, items, and trace re-fetchable.
    detail = client.get(f"/api/executions/{execution_id}", headers=headers).json()
    assert detail["data"]["results"]["outputs"]["sd2"]["main"][0]["lead_email"] == "jane@example.com"
    items = client.get(f"/api/executions/{execution_id}/items", headers=headers).json()
    item_ids = [i["node_id"] for i in items["data"]]
    assert item_ids == ["trigger", "sd1", "sf", "sd2"]
    sf_item = next(i for i in items["data"] if i["node_id"] == "sf")
    assert sf_item["outputs"]["main"][0]["record"]["Email"] == "jane@example.com"
    sd2_item = next(i for i in items["data"] if i["node_id"] == "sd2")
    assert sd2_item["outputs"]["main"][0]["lead_email"] == "jane@example.com"
    assert sd2_item["outputs"]["main"][0]["lead_name"] == "Jane Doe"
    trace = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()
    trace_ids = [s["node_id"] for s in trace["data"]["steps"]]
    assert trace_ids == ["trigger", "sd1", "sf", "sd2"]

    # Execution history: listed for the workflow.
    history = client.get(f"/api/executions?workflow_id={wf_id}", headers=headers).json()
    entry = next(e for e in history["data"] if e["id"] == execution_id)
    assert entry["status"] == "success"
    assert entry["workflow_id"] == wf_id

    # No credentials anywhere.
    _assert_no_secrets(data, "execution detail")
    _assert_no_secrets(items, "execution items")
    _assert_no_secrets(trace, "execution trace")
    _assert_no_secrets(history, "execution history")


# ----------------------------------------------------------------------
# Retry: 429 on the search is retried, DAG completes
# ----------------------------------------------------------------------


def test_dag_retries_on_429_and_completes(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_dag_sf_retry"
    settings = {"retry_max_attempts": 3, "retry_backoff_seconds": 0.01}
    client.post("/api/workflows", json=_dag_workflow(meta["id"], wf_id, sf_settings=settings), headers=headers)

    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(429, json=[{"message": "API_REQUESTS_EXCEEDED"}], request=httpx.Request("GET", "http://fake")),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qabc123"}]}),
        _json_response(200, LEAD_RECORD),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data=INPUT)
    finally:
        patcher.stop()

    assert data["status"] == "success"
    assert data["results"]["outputs"]["sd2"]["main"][0]["found"] is True
    query_calls = [c for c in fake.calls if "/query" in c[1]]
    assert len(query_calls) == 2  # failed attempt + retried attempt

    history = client.get(f"/api/executions?workflow_id={wf_id}", headers=headers).json()
    entry = next(e for e in history["data"] if e["id"] == execution_id)
    assert entry["status"] == "success"
    _assert_no_secrets(data, "execution detail for retried run")


# ----------------------------------------------------------------------
# Timeout: transport error fails the DAG, retryable, downstream skipped
# ----------------------------------------------------------------------


def test_dag_timeout_fails_after_search(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_dag_sf_timeout"
    client.post("/api/workflows", json=_dag_workflow(meta["id"], wf_id), headers=headers)

    patcher, _fake = _patch_client([_json_response(200, TOKEN_BODY)], client_cls=RaisingFakeHTTPClient)
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id, input_data=INPUT)
    finally:
        patcher.stop()

    assert data["status"] == "failed"
    assert data["error"]["code"] == "CONNECTOR_TIMEOUT"
    assert data["error"]["node_id"] == "sf"
    assert data["error"]["retryable"] is True
    assert data["node_statuses"]["sf"] == "error"
    assert "sd2" not in data["results"]["outputs"]  # downstream never ran

    history = client.get(f"/api/executions?workflow_id={wf_id}", headers=headers).json()
    entry = next(e for e in history["data"] if e["id"] == execution_id)
    assert entry["status"] == "failed"
    _assert_no_secrets(data, "execution detail for timeout")