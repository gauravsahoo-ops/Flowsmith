"""Salesforce credentials + authentication tests (Phase 5, spec 12, 29):

- valid / invalid / missing credentials
- end-to-end credential resolution through the real stack (API -> queue
  -> worker -> engine -> SalesforceConnector)
- secret protection: no secrets in frontend responses, workflow JSON,
  execution history, trace or logs.

The Salesforce auth method is the OAuth2 username-password (resource
owner) grant against /services/oauth2/token (production
https://login.salesforce.com, sandbox https://test.salesforce.com via
instance_url). No live sandbox exists in this environment, so the
external API is scripted at the SafeHTTPClient seam.
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
from app.db import get_session
from app.models import Credential, Execution, WorkflowRecord
from app.security.crypto import decrypt_text
from app.security.safe_http_client import SafeHTTPClient
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


class FakeSFHTTPClient:
    """Scripted SafeHTTPClient replacement: token + data API responses."""

    def __init__(self, responses: list[tuple[httpx.Response, dict[str, Any] | None]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        self.calls.append((method, url, {"params": params, "json": json, "data": data, "headers": headers}))
        response, _ = self.responses.pop(0)
        return response


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _patch_client(responses):
    fake = FakeSFHTTPClient(responses)
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


def _create_sf_credential(client, headers, data=SF_DATA):
    resp = client.post("/api/credentials", json={"name": "SF Prod", "type": "salesforce", "data": data}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _sf_workflow(credential_id: str, workflow_id: str = "wf_sf_cred") -> dict:
    return {
        "id": workflow_id,
        "name": "SF Query",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "sf",
                "type": "salesforce",
                "parameters": {"operation": "query", "soql": "SELECT Id, Name FROM Account LIMIT 1"},
                "settings": {},
                "credentials": {"salesforce": credential_id},
            },
        ],
        "connections": [{"source": "trigger", "target": "sf"}],
        "settings": {},
    }


def _run_and_poll(client, headers, wf_id="wf_sf_cred"):
    resp = client.post(f"/api/workflows/{wf_id}/run", json={}, headers=headers)
    assert resp.status_code == 202, resp.text
    execution_id = resp.json()["data"]["execution_id"]
    deadline = time.monotonic() + 15
    status = "running"
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        status = data["status"]
        if status not in ("running", "queued", "cancelling"):
            return execution_id, data
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish: {status}")


def _assert_no_secrets(value: Any, where: str) -> None:
    text = json.dumps(value, default=str)
    for marker in SECRET_MARKERS:
        assert marker not in text, f"secret {marker!r} leaked into {where}"


# ----------------------------------------------------------------------
# Valid / invalid credentials
# ----------------------------------------------------------------------


def test_valid_salesforce_credential_created(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    assert set(meta) == {"id", "name", "type"}
    assert meta["type"] == "salesforce"

    db = get_session()
    try:
        rec = db.get(Credential, meta["id"])
        assert rec is not None
        assert b"S3CR3T_CLIENT_SECRET_ZZZ" not in rec.data  # encrypted at rest
        plaintext = decrypt_text(rec.data)
        assert "S3CR3T_CLIENT_SECRET_ZZZ" in plaintext  # round-trips
    finally:
        db.close()


@pytest.mark.parametrize("field", ["client_id", "client_secret", "username", "password"])
def test_invalid_salesforce_credential_missing_field(client, field):
    headers = _setup(client)
    data = {k: v for k, v in SF_DATA.items() if k != field}
    resp = client.post("/api/credentials", json={"name": "SF", "type": "salesforce", "data": data}, headers=headers)
    assert resp.status_code == 422, resp.text


def test_invalid_salesforce_credential_empty_instance_url(client):
    headers = _setup(client)
    data = {**SF_DATA, "instance_url": ""}
    resp = client.post("/api/credentials", json={"name": "SF", "type": "salesforce", "data": data}, headers=headers)
    assert resp.status_code == 422


def test_salesforce_credential_type_catalog_marks_secrets(client):
    headers = _setup(client)
    types = client.get("/api/credentials/types", headers=headers).json()["data"]
    sf = next(t for t in types if t["type"] == "salesforce")
    assert set(sf["secret_fields"]) == {"client_secret", "password", "refresh_token"}
    props = sf["parameters_schema"]["properties"]
    assert {"instance_url", "client_id", "client_secret", "username", "password", "refresh_token"} <= set(props)


# ----------------------------------------------------------------------
# Refresh-token credentials (Phase 20)
# ----------------------------------------------------------------------

REFRESH_SF_DATA = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "cid_123",
    "client_secret": "S3CR3T_CLIENT_SECRET_ZZZ",
    "username": "",
    "password": "",
    "refresh_token": "00D_REFRESH_TOKEN_XYZ",
    "api_version": "v63.0",
}


def test_refresh_token_credential_created(client):
    headers = _setup(client)
    resp = client.post(
        "/api/credentials",
        json={"name": "SF Refresh", "type": "salesforce", "data": REFRESH_SF_DATA},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    db = get_session()
    try:
        rec = db.get(Credential, resp.json()["data"]["id"])
        assert b"00D_REFRESH_TOKEN_XYZ" not in rec.data  # encrypted at rest
        assert "00D_REFRESH_TOKEN_XYZ" in decrypt_text(rec.data)
    finally:
        db.close()


@pytest.mark.parametrize("data", [
    {"password": ""},                       # password empty (username present)
    {"username": ""},                       # username empty (password present)
    {"username": "", "password": ""},       # neither method
])
def test_salesforce_credential_requires_an_auth_method(client, data):
    headers = _setup(client)
    payload = {**SF_DATA, **data}
    resp = client.post(
        "/api/credentials",
        json={"name": "SF", "type": "salesforce", "data": payload},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_refresh_token_flow_full_stack(client):
    """A refresh-token credential authenticates through the real stack:
    API -> queue -> worker -> connector, using grant_type=refresh_token."""
    headers = _setup(client)
    meta = client.post(
        "/api/credentials",
        json={"name": "SF Refresh", "type": "salesforce", "data": REFRESH_SF_DATA},
        headers=headers,
    ).json()["data"]
    client.post("/api/workflows", json=_sf_workflow(meta["id"]), headers=headers)

    patcher, fake = _patch_client([
        (httpx.Response(200, json={"access_token": "tok_refresh", "instance_url": "https://myorg.salesforce.com"},
                        request=httpx.Request("GET", "http://fake")), None),
        (httpx.Response(200, json={"totalSize": 1, "done": True, "records": [{"Id": "001", "Name": "Acme"}]},
                        request=httpx.Request("GET", "http://fake")), None),
    ])
    try:
        execution_id, data = _run_and_poll(client, headers)
    finally:
        patcher.stop()

    assert data["status"] == "success"
    method, url, kwargs = fake.calls[0]
    assert url == "https://login.salesforce.com/services/oauth2/token"
    assert "grant_type=refresh_token" in kwargs["data"]
    assert "refresh_token=00D_REFRESH_TOKEN_XYZ" in kwargs["data"]
    assert "username" not in kwargs["data"]
    assert fake.calls[1][2]["headers"]["Authorization"] == "Bearer tok_refresh"


# ----------------------------------------------------------------------
# Missing credentials (full stack)
# ----------------------------------------------------------------------


def test_missing_credential_fails_run_with_typed_error(client):
    headers = _setup(client)
    client.post("/api/workflows", json=_sf_workflow("cred_ghost"), headers=headers)

    resp = client.post("/api/workflows/wf_sf_cred/run", json={}, headers=headers)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_WORKFLOW"
    issues = detail.get("issues", [])
    assert any(i["code"] == "CREDENTIAL_NOT_FOUND" and "cred_ghost" in i["message"] for i in issues)


def test_missing_credential_fails_without_network(client):
    """A missing credential must fail before any external API call."""
    headers = _setup(client)
    client.post("/api/workflows", json=_sf_workflow("cred_ghost"), headers=headers)
    patcher, fake = _patch_client([])
    try:
        resp = client.post("/api/workflows/wf_sf_cred/run", json={}, headers=headers)
    finally:
        patcher.stop()
    assert resp.status_code == 422
    assert fake.calls == []  # no token request ever happened


# ----------------------------------------------------------------------
# Resolution + secret protection (full stack)
# ----------------------------------------------------------------------


def test_credential_resolution_and_secret_protection(client):
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)

    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    query_response = _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "001", "Name": "Acme"}]})
    patcher, fake = _patch_client([(token_response, None), (query_response, None)])
    try:
        client.post("/api/workflows", json=_sf_workflow(meta["id"]), headers=headers)
        execution_id, data = _run_and_poll(client, headers)
    finally:
        patcher.stop()

    # The run succeeded through the real resolver -> connector path.
    assert data["status"] == "success"
    assert data["node_statuses"]["sf"] == "success"
    assert data["results"]["outputs"]["sf"]["main"][0]["records"][0]["Name"] == "Acme"

    # Resolution proof: the token request carried the decrypted secrets.
    token_call = next(c for c in fake.calls if "/services/oauth2/token" in c[1])
    assert "client_secret=S3CR3T_CLIENT_SECRET_ZZZ" in token_call[2]["data"]
    assert "P4SS_%2B_TOK3N_ZZZ" in token_call[2]["data"]  # URL-encoded form

    # Secret protection everywhere else:
    _assert_no_secrets(data, "execution detail")

    creds_list = client.get("/api/credentials", headers=headers).json()
    _assert_no_secrets(creds_list, "credentials list")

    wf_resp = client.get("/api/workflows/wf_sf_cred", headers=headers)
    assert wf_resp.status_code == 200
    wf_body = wf_resp.json()
    node = next(n for n in wf_body["data"]["nodes"] if n["id"] == "sf")
    assert node["credentials"] == {"salesforce": meta["id"]}  # reference only
    _assert_no_secrets(wf_body, "workflow JSON")

    history = client.get("/api/executions?workflow_id=wf_sf_cred", headers=headers).json()
    _assert_no_secrets(history, "execution history list")

    trace = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()
    _assert_no_secrets(trace, "execution trace")

    items = client.get(f"/api/executions/{execution_id}/items", headers=headers).json()
    _assert_no_secrets(items, "execution items")

    # Stored rows: the workflow snapshot and execution snapshot hold
    # credential references, never secrets.
    db = get_session()
    try:
        wf_row = db.get(WorkflowRecord, "wf_sf_cred")
        assert wf_row is not None
        _assert_no_secrets(wf_row.data, "stored workflow record")

        exec_row = db.get(Execution, execution_id)
        assert exec_row is not None
        _assert_no_secrets(exec_row.workflow_data, "stored execution snapshot")
        _assert_no_secrets(exec_row.results or {}, "stored execution results")
        _assert_no_secrets(exec_row.trace or [], "stored execution trace")
    finally:
        db.close()


# ----------------------------------------------------------------------
# Redaction units
# ----------------------------------------------------------------------


def test_sensitive_headers_redacted():
    redacted = SafeHTTPClient._redact_sensitive_headers({
        "Authorization": "Bearer tok123",
        "x-api-key": "k123",
        "Cookie": "session=abc",
        "X-Client-Secret": "S3CR3T_CLIENT_SECRET_ZZZ",
        "Content-Type": "application/json",
    })
    assert redacted["Authorization"] == "***REDACTED***"
    assert redacted["x-api-key"] == "***REDACTED***"
    assert redacted["Cookie"] == "***REDACTED***"
    assert redacted["X-Client-Secret"] == "***REDACTED***"
    assert redacted["Content-Type"] == "application/json"


def test_sanitize_for_logging_masks_secrets():
    sanitized = SafeHTTPClient._sanitize_for_logging({
        "token": "aB3dE9fG2hJ4kL6mN8pQ0rS2tU4vW6xY",
        "password": "P4SS_+_TOK3N_ZZZ",
        "safe": "hello",
    })
    assert sanitized["safe"] == "hello"
    # Long opaque alphanumeric strings (potential keys/tokens) are masked.
    masked = sanitized["token"]
    assert masked == "aB3dE9…6xY"  # first 6 + … + last 3
    # Short non-opaque strings pass through unchanged.
    assert sanitized["password"] == "P4SS_+_TOK3N_ZZZ"


def test_credential_errors_do_not_expose_secrets(client):
    """Resolution failures surface ids only, never names or stored values."""
    headers = _setup(client)
    meta = _create_sf_credential(client, headers)
    db = get_session()
    try:
        rec = db.get(Credential, meta["id"])
        assert rec is not None
        rec.name = "S3CR3T_CLIENT_SECRET_ZZZ"  # adversarial: secret as the name
        db.commit()
    finally:
        db.close()
    # A foreign user referencing it gets a typed failure at run time.
    token_b = register(client, email="b@b.com", password="Password123!")["token"]
    client.post("/api/workflows", json=_sf_workflow(meta["id"]), headers=auth_headers(token_b))
    resp = client.post("/api/workflows/wf_sf_cred/run", json={}, headers=auth_headers(token_b))
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_WORKFLOW"
    text = json.dumps(detail)
    # Neither the secret values nor the adversarial credential name leak.
    assert "P4SS_+_TOK3N_ZZZ" not in text
    assert "S3CR3T_CLIENT_SECRET_ZZZ" not in text