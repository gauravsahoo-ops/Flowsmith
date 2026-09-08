"""Phase 24: the primary Salesforce demonstration workflow — Lead Sync.

Business workflow (the "REAL BUSINESS WORKFLOW" milestone):

    Manual Trigger
          |
    Set Data (enrich: FirstName/LastName/Email/Company/Phone/LeadSource)
          |
    Salesforce Search Lead (by Email)
          |
        IF (found == true)
       /                  \
      YES                 NO
      |                    |
    Update Lead         Create Lead

Each test drives the whole production path — API -> job queue -> worker
-> DAG engine -> connector -> (mocked) Salesforce REST API -> database
-> execution history/trace/items — exactly as a UI-created workflow
would (spec 9, 13, 14, 24, 25, 51; Phase 23 connector framework).

The Salesforce HTTP layer is mocked (SafeHTTPClient patch, as in the
other salesforce suites) so both branches are verified deterministically
without a real org; see docs/PHASE_24.md for wiring real credentials.

Verified per path:
- DAG branching (IF routes to update vs create; the other leg skips)
- data mapping (set_data -> SOQL search value, -> record payloads)
- Salesforce API (token, query/get, PATCH vs POST, bearer auth)
- worker execution (202 queued -> success)
- execution history (list/detail/trace/items, no secret leakage)
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

WORKFLOW_ID = "wf_salesforce_lead_sync"

# A lead that already exists in "Salesforce".
EXISTING_LEAD = {
    "Id": "00Qabc123456789",
    "FirstName": "Jane",
    "LastName": "Doe",
    "Email": "jane@example.com",
    "Company": "Acme",
    "Phone": "+1-555-0100",
    "LeadSource": "Web",
}

# Manual-run trigger input (what a sales rep enters in the Run dialog).
INPUT = {
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane@example.com",
    "company": "Acme",
    "phone": "+1-555-0100",
}

# What the enrich (set_data) node produces -> mapped into the record payloads.
ENRICHED = {
    "FirstName": "Jane",
    "LastName": "Doe",
    "Email": "jane@example.com",
    "Company": "Acme",
    "Phone": "+1-555-0100",
    "LeadSource": "Web",
}

UPDATE_FIELDS = {"Company": "Acme", "Phone": "+1-555-0100", "LeadSource": "Web"}


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


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _patch_client(responses: list[httpx.Response]):
    fake = FakeSFHTTPClient(responses)
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
    resp = client.post(
        "/api/credentials",
        json={"name": "SF Prod", "type": "salesforce", "data": SF_DATA},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _lead_sync_workflow(credential_id: str, workflow_id: str = WORKFLOW_ID) -> dict:
    """The primary Salesforce demonstration workflow (Phase 24)."""
    return {
        "id": workflow_id,
        "name": "Salesforce Lead Sync",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "enrich",
                "type": "set_data",
                "parameters": {
                    "mode": "merge",
                    "fields": {
                        "FirstName": "{{ $json.first_name }}",
                        "LastName": "{{ $json.last_name }}",
                        "Email": "{{ $json.email }}",
                        "Company": "{{ $json.company }}",
                        "Phone": "{{ $json.phone }}",
                        "LeadSource": "Web",
                    },
                },
            },
            {
                "id": "sf_search",
                "type": "salesforce",
                "parameters": {
                    "operation": "search",
                    "object_name": "Lead",
                    "search_field": "Email",
                    "search_value": "{{ $node.enrich.json.Email }}",
                },
                "settings": {},
                "credentials": {"salesforce": credential_id},
            },
            {
                "id": "route",
                "type": "if_condition",
                "parameters": {
                    "condition": {"left": "$json.found", "operator": "equals", "right": True},
                },
            },
            {
                "id": "sf_update",
                "type": "salesforce",
                "parameters": {
                    "operation": "update",
                    "object_name": "Lead",
                    "record_id": "{{ $node.sf_search.json.record.Id }}",
                    "record": {
                        "Company": "{{ $node.enrich.json.Company }}",
                        "Phone": "{{ $node.enrich.json.Phone }}",
                        "LeadSource": "{{ $node.enrich.json.LeadSource }}",
                    },
                },
                "settings": {},
                "credentials": {"salesforce": credential_id},
            },
            {
                "id": "sf_create",
                "type": "salesforce",
                "parameters": {
                    "operation": "create",
                    "object_name": "Lead",
                    "record": {
                        "FirstName": "{{ $node.enrich.json.FirstName }}",
                        "LastName": "{{ $node.enrich.json.LastName }}",
                        "Email": "{{ $node.enrich.json.Email }}",
                        "Company": "{{ $node.enrich.json.Company }}",
                        "Phone": "{{ $node.enrich.json.Phone }}",
                        "LeadSource": "{{ $node.enrich.json.LeadSource }}",
                    },
                },
                "settings": {},
                "credentials": {"salesforce": credential_id},
            },
        ],
        "connections": [
            {"source": "trigger", "target": "enrich"},
            {"source": "enrich", "target": "sf_search"},
            {"source": "sf_search", "target": "route"},
            {"source": "route", "target": "sf_update", "sourceHandle": "true"},
            {"source": "route", "target": "sf_create", "sourceHandle": "false"},
        ],
        "settings": {},
    }


def _run_and_poll(client, headers, wf_id, input_data=None) -> tuple[str, dict]:
    body = {"data": input_data} if input_data is not None else {}
    resp = client.post(f"/api/workflows/{wf_id}/run", json=body, headers=headers)
    assert resp.status_code == 202, resp.text
    execution_id = resp.json()["data"]["execution_id"]
    deadline = time.monotonic() + 15
    data: dict[str, Any] = {}
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


def _token_call(fake) -> tuple[str, str, dict[str, Any]]:
    return next(c for c in fake.calls if "/services/oauth2/token" in c[1])


def _query_call(fake) -> tuple[str, str, dict[str, Any]]:
    return next(c for c in fake.calls if "/query" in c[1])


# ----------------------------------------------------------------------
# Path 1: EXISTING lead -> search finds it -> UPDATE branch
# ----------------------------------------------------------------------


def test_existing_lead_routes_to_update(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    client.post("/api/workflows", json=_lead_sync_workflow(meta["id"]), headers=headers)

    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qabc123456789"}]}),
        _json_response(200, EXISTING_LEAD),
        httpx.Response(204, request=httpx.Request("GET", "http://fake")),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, WORKFLOW_ID, input_data=INPUT)
    finally:
        patcher.stop()

    # Worker execution: the whole DAG settled as success.
    assert data["status"] == "success"
    assert data["node_statuses"] == {
        "trigger": "success",
        "enrich": "success",
        "sf_search": "success",
        "route": "success",
        "sf_update": "success",
        "sf_create": "skipped",
    }

    # DAG branching: the search result drove the IF; the create leg never ran.
    outputs = data["results"]["outputs"]
    search_output = {"found": True, "record": EXISTING_LEAD, "object_name": "Lead", "search_field": "Email"}
    assert outputs["route"]["true"] == [search_output]
    assert outputs["route"]["false"] == []
    assert "sf_create" not in outputs  # skipped leg has no output

    # Data mapping: set_data output fed the SOQL search value.
    query_call = _query_call(fake)
    assert query_call[2]["params"]["q"] == (
        "SELECT Id FROM Lead WHERE Email = 'jane@example.com' LIMIT 1"
    )

    # Salesforce API: update = PATCH with the resolved record id + fields.
    update_call = fake.calls[3]
    assert update_call[0] == "PATCH"
    assert update_call[1] == (
        "https://myorg.salesforce.com/services/data/v63.0/sobjects/Lead/00Qabc123456789"
    )
    assert update_call[2]["json"] == UPDATE_FIELDS
    assert update_call[2]["headers"]["Authorization"] == "Bearer tok123"

    # Credential resolution: token request carried the decrypted secrets.
    assert "client_secret=S3CR3T_CLIENT_SECRET_ZZZ" in _token_call(fake)[2]["data"]

    # Update node output exposed to the execution result.
    assert outputs["sf_update"]["main"] == [{"id": "00Qabc123456789", "success": True}]

    # Execution history + persistence: detail, items, trace re-fetchable.
    detail = client.get(f"/api/executions/{execution_id}", headers=headers).json()
    assert detail["data"]["results"]["outputs"]["sf_update"]["main"][0]["id"] == "00Qabc123456789"
    items = client.get(f"/api/executions/{execution_id}/items", headers=headers).json()
    item_ids = [i["node_id"] for i in items["data"]]
    assert item_ids == ["trigger", "enrich", "sf_search", "route", "sf_update"]
    assert "sf_create" not in item_ids  # skipped leg produced no items
    trace = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()
    steps = {s["node_id"]: s for s in trace["data"]["steps"]}
    assert set(steps) == {"trigger", "enrich", "sf_search", "route", "sf_update", "sf_create"}
    assert steps["sf_update"]["status"] == "success"
    assert steps["sf_create"]["status"] == "skipped"
    history = client.get(f"/api/executions?workflow_id={WORKFLOW_ID}", headers=headers).json()
    entry = next(e for e in history["data"] if e["id"] == execution_id)
    assert entry["status"] == "success"
    assert entry["workflow_id"] == WORKFLOW_ID

    # No credentials anywhere.
    _assert_no_secrets(data, "execution detail")
    _assert_no_secrets(items, "execution items")
    _assert_no_secrets(trace, "execution trace")
    _assert_no_secrets(history, "execution history")


# ----------------------------------------------------------------------
# Path 2: MISSING lead -> search finds nothing -> CREATE branch
# ----------------------------------------------------------------------


def test_missing_lead_routes_to_create(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    client.post("/api/workflows", json=_lead_sync_workflow(meta["id"]), headers=headers)

    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
        _json_response(201, {"id": "00Qnew456", "success": True}),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, WORKFLOW_ID, input_data=INPUT)
    finally:
        patcher.stop()

    # Worker execution: settled as success.
    assert data["status"] == "success"
    assert data["node_statuses"] == {
        "trigger": "success",
        "enrich": "success",
        "sf_search": "success",
        "route": "success",
        "sf_create": "success",
        "sf_update": "skipped",
    }

    # DAG branching: no record -> false branch -> create; update leg skipped.
    outputs = data["results"]["outputs"]
    search_output = {"found": False, "record": None, "object_name": "Lead", "search_field": "Email"}
    assert outputs["route"]["true"] == []
    assert outputs["route"]["false"] == [search_output]
    assert "sf_update" not in outputs

    # Data mapping: the SOQL search used the enriched email.
    assert _query_call(fake)[2]["params"]["q"] == (
        "SELECT Id FROM Lead WHERE Email = 'jane@example.com' LIMIT 1"
    )

    # Salesforce API: create = POST with the fully resolved record body.
    create_call = fake.calls[2]
    assert create_call[0] == "POST"
    assert create_call[1] == "https://myorg.salesforce.com/services/data/v63.0/sobjects/Lead"
    assert create_call[2]["json"] == ENRICHED
    assert create_call[2]["headers"]["Authorization"] == "Bearer tok123"
    assert "client_secret=S3CR3T_CLIENT_SECRET_ZZZ" in _token_call(fake)[2]["data"]

    # Create node output exposed to the execution result.
    assert outputs["sf_create"]["main"] == [{"id": "00Qnew456", "success": True}]

    # Execution history: listed for the workflow.
    history = client.get(f"/api/executions?workflow_id={WORKFLOW_ID}", headers=headers).json()
    entry = next(e for e in history["data"] if e["id"] == execution_id)
    assert entry["status"] == "success"
    trace = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()
    steps = {s["node_id"]: s for s in trace["data"]["steps"]}
    assert steps["sf_create"]["status"] == "success"
    assert steps["sf_update"]["status"] == "skipped"

    # No credentials anywhere.
    _assert_no_secrets(data, "execution detail")
    _assert_no_secrets(history, "execution history")
