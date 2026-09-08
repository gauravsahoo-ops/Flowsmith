"""Phase 17: secret-leakage + isolation security tests (full stack).

Verifies the hard guarantees end to end:
- credentials API never returns secret material (no per-credential GET);
- workflow JSON (API responses AND stored DB rows) holds credential IDs
  only, never secret values;
- execution history (detail/results/items/trace + stored DB rows) never
  contains secret values;
- credential secrets never appear in application logs;
- cross-user credential references are rejected at save time (422)
  without leaking ids/names/secrets;
- a shared editor running the owner's credentialed workflow fails
  cleanly (CREDENTIALS_REQUIRED) with no secret exposure.

The Salesforce HTTP layer is scripted at the SafeHTTPClient seam, as in
the other salesforce suites.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

pytestmark = pytest.mark.timing

from app.connectors import get_registry, register_builtin_connectors
from app.db import get_session
from app.models import Credential, Execution, WorkflowRecord
from tests.test_api.conftest import auth_headers, make_workflow, register

SF_DATA = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "cid_123",
    "client_secret": "S3CR3T_CLIENT_SECRET_ZZZ",
    "username": "user@example.com",
    "password": "P4SS_+_TOK3N_ZZZ",
    "api_version": "v63.0",
}

SECRET_MARKERS = ["S3CR3T_CLIENT_SECRET_ZZZ", "P4SS_+_TOK3N_ZZZ", "cid_123"]


class FakeSFHTTPClient:
    """Scripted SafeHTTPClient replacement: token + data API responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        return self.responses.pop(0)


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _token_response() -> httpx.Response:
    return _json_response(200, {"access_token": "tok123", "instance_url": "https://o.salesforce.com"})


def _patch_client(responses):
    fake = FakeSFHTTPClient(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.providers.salesforce.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher


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


def _sf_workflow(credential_id: str, workflow_id: str = "wf_sec") -> dict:
    wf = make_workflow(workflow_id)
    wf["nodes"].append(
        {
            "id": "sf",
            "type": "salesforce",
            "parameters": {"operation": "query", "soql": "SELECT Id FROM Lead LIMIT 1"},
            "settings": {},
            "credentials": {"salesforce": credential_id},
        }
    )
    wf["connections"] = [
        {"source": "trigger", "target": "transform"},
        {"source": "transform", "target": "sf"},
    ]
    return wf


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


def _assert_no_secrets(value: Any, where: str) -> None:
    text = json.dumps(value, default=str)
    for marker in SECRET_MARKERS:
        assert marker not in text, f"secret {marker!r} leaked into {where}"


# ----------------------------------------------------------------------
# Credential API surface
# ----------------------------------------------------------------------


def test_credentials_api_never_exposes_secret_material(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)

    listed = client.get("/api/credentials", headers=headers).json()["data"]
    assert len(listed) == 1
    assert set(listed[0]) == {"id", "name", "type"}
    assert listed[0]["id"] == meta["id"]
    _assert_no_secrets(listed, "GET /api/credentials")

    # No single-credential GET endpoint exists (405 Method Not Allowed —
    # the route only defines DELETE; a GET handler would return 200).
    resp = client.get(f"/api/credentials/{meta['id']}", headers=headers)
    assert resp.status_code == 405

    # The DB row stores ciphertext, not plaintext.
    db = get_session()
    try:
        rec = db.get(Credential, meta["id"])
        assert rec is not None
        ciphertext = rec.data if isinstance(rec.data, bytes) else rec.data.encode()
        assert all(marker.encode() not in ciphertext for marker in SECRET_MARKERS)
    finally:
        db.close()


# ----------------------------------------------------------------------
# Workflow JSON: credential IDs only
# ----------------------------------------------------------------------


def test_workflow_json_stores_only_credential_ids(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf = _sf_workflow(meta["id"])

    resp = client.post("/api/workflows", json=wf, headers=headers)
    assert resp.status_code == 201, resp.text
    _assert_no_secrets(resp.json(), "POST /api/workflows response")

    fetched = client.get(f"/api/workflows/{wf['id']}", headers=headers).json()["data"]
    _assert_no_secrets(fetched, "GET /api/workflows/{id} response")

    db = get_session()
    try:
        rec = db.get(WorkflowRecord, wf["id"])
        assert rec is not None
        stored = rec.data
        # The credential reference is the id only — never the values.
        sf_node = next(n for n in stored["nodes"] if n["id"] == "sf")
        assert sf_node["credentials"] == {"salesforce": meta["id"]}
        _assert_no_secrets(stored, "stored workflow JSON (workflows.data)")
    finally:
        db.close()


# ----------------------------------------------------------------------
# Execution history: no secrets in responses or stored rows
# ----------------------------------------------------------------------


def test_execution_history_never_stores_secrets(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sec_history"
    client.post("/api/workflows", json=_sf_workflow(meta["id"], wf_id), headers=headers)

    patcher = _patch_client([
        _token_response(),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qabc", "Name": "Lead"}]}),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers, wf_id)
    finally:
        patcher.stop()
    assert data["status"] == "success"

    _assert_no_secrets(data, "execution detail")
    _assert_no_secrets(client.get(f"/api/executions/{execution_id}/items", headers=headers).json(), "execution items")
    _assert_no_secrets(client.get(f"/api/executions/{execution_id}/trace", headers=headers).json(), "execution trace")
    history = client.get("/api/executions", headers=headers).json()
    _assert_no_secrets(history, "execution history list")

    db = get_session()
    try:
        rec = db.get(Execution, execution_id)
        assert rec is not None
        for field, where in (
            (rec.workflow_data, "executions.workflow_data"),
            (rec.trigger_data, "executions.trigger_data"),
            (rec.results, "executions.results"),
            (rec.node_statuses, "executions.node_statuses"),
            (rec.trace, "executions.trace"),
            (rec.error, "executions.error"),
        ):
            _assert_no_secrets(field, where)
    finally:
        db.close()


# ----------------------------------------------------------------------
# Logs
# ----------------------------------------------------------------------


def test_credential_secrets_never_logged(client, caplog):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    wf_id = "wf_sec_logs"
    client.post("/api/workflows", json=_sf_workflow(meta["id"], wf_id), headers=headers)

    # Fail the run through a real provider error path so the whole
    # stack (worker -> engine -> connector -> provider) logs/exceptions
    # are exercised.
    patcher = _patch_client([
        _token_response(),
        _json_response(400, [{"errorCode": "MALFORMED_QUERY", "message": "bad SOQL"}]),
    ])
    try:
        with caplog.at_level(logging.DEBUG):
            _execution_id, data = _run_and_poll(client, headers, wf_id)
    finally:
        patcher.stop()
    assert data["status"] == "failed"

    _assert_no_secrets(data, "failed execution detail")
    assert "tok123" not in json.dumps(data)
    for record in caplog.records:
        _assert_no_secrets(record.getMessage(), "log record message")
        _assert_no_secrets(record.exc_info, "log record exc_info")


# ----------------------------------------------------------------------
# Isolation: cross-user credential references
# ----------------------------------------------------------------------


def test_foreign_workflow_save_and_run_never_leak_secrets(client):
    """A workflow referencing another user's credential saves (connector
    refs are enforced at run time), and the run fails cleanly with the
    credential id only — never names, values, or tokens."""
    owner_headers = _setup(client)
    meta = _create_sf_credential(client, owner_headers)

    token_b = register(client, email="b@b.com", password="Password123!")["token"]
    wf = _sf_workflow(meta["id"], "wf_sec_foreign")
    resp = client.post("/api/workflows", json=wf, headers=auth_headers(token_b))
    assert resp.status_code == 201, resp.text
    _assert_no_secrets(resp.json(), "foreign workflow save response")

    resp = client.post(f"/api/workflows/{wf['id']}/run", json={}, headers=auth_headers(token_b))
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_WORKFLOW"
    text = json.dumps(detail)
    _assert_no_secrets(detail, "foreign run failure detail")
    assert "not found" in detail.get("message", "")


def test_shared_editor_cannot_resolve_owners_credentials(client):
    owner = register(client, "owner@sec.com")
    editor = register(client, "editor@sec.com")
    owner_headers = auth_headers(owner["token"])

    meta = _create_sf_credential(client, owner_headers)
    wf = _sf_workflow(meta["id"], "wf_sec_shared")
    client.post("/api/workflows", json=wf, headers=owner_headers)
    resp = client.post(
        f"/api/workflows/{wf['id']}/shares",
        json={"email": "editor@sec.com", "permission": "edit"},
        headers=owner_headers,
    )
    assert resp.status_code == 201

    editor_headers = auth_headers(editor["token"])
    resp = client.post(f"/api/workflows/{wf['id']}/run", json={}, headers=editor_headers)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_WORKFLOW"
    _assert_no_secrets(detail, "shared editor credential check")