"""Environment variables end-to-end (Phase 31).

Proves the full {{ $env.KEY }} flow through the real stack:

1. Workspace-scoped variables are created via the API (encrypted at rest).
2. A workflow assigned to the workspace references them via expressions.
3. The worker resolves the decrypted values at execution time.
4. Resolved values reach the node (http_request) — verified via a fake
   HTTP client that records the outgoing request.
5. Secret values never appear in the persisted execution record/trace.

Tenant isolation: users outside the workspace cannot list its variables.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import httpx
import pytest

pytestmark = pytest.mark.timing

from tests.test_api.conftest import auth_headers, register


class RecordingHTTPClient:
    """Records outgoing requests; returns a canned 200 JSON response."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        return httpx.Response(200, json={"ok": True}, request=httpx.Request(method, url))


def _setup_ws(client, email: str) -> tuple[dict[str, str], str]:
    """Register a user and create an org + workspace; returns (headers, ws_id)."""
    data = register(client, email=email)
    headers = auth_headers(data["token"])
    org_id = client.post("/api/organizations", json={"name": "Env Org"}, headers=headers).json()["data"]["id"]
    ws_id = client.post(
        "/api/workspaces", json={"name": "Env WS", "organization_id": org_id}, headers=headers
    ).json()["data"]["id"]
    return headers, ws_id


def _create_env(client, headers, ws_id: str, key: str, value: str, *, secret: bool = False) -> None:
    resp = client.post(
        "/api/environments",
        json={"workspace_id": ws_id, "key": key, "value": value, "is_secret": secret},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def _poll(client, execution_id: str, headers: dict, timeout_s: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/api/executions/{execution_id}", headers=headers).json()
        if "data" in body:
            status = body["data"]["status"]
            if status not in ("running", "queued", "cancelling"):
                return body["data"]
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish in time")


def test_env_vars_resolve_in_execution(client):
    headers, ws_id = _setup_ws(client, "envexec1@test.com")
    _create_env(client, headers, ws_id, "API_URL", "https://api.example.test/endpoint")
    _create_env(client, headers, ws_id, "API_TOKEN", "S3CR3T-TOKEN-XYZ", secret=True)

    wf = {
        "id": "wf_env",
        "name": "Env workflow",
        "workspace_id": ws_id,
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "call",
                "type": "http_request",
                "parameters": {
                    "method": "GET",
                    "url": "{{ $env.API_URL }}",
                    "headers": {"Authorization": "Bearer {{ $env.API_TOKEN }}"},
                },
            },
        ],
        "connections": [{"source": "trigger", "target": "call"}],
        "settings": {},
    }
    resp = client.post("/api/workflows", json=wf, headers=headers)
    assert resp.status_code == 201, resp.text

    fake = RecordingHTTPClient()
    with patch("app.execution_runtime._http_client", return_value=fake):
        run = client.post("/api/workflows/wf_env/run", json={}, headers=headers).json()["data"]
        data = _poll(client, run["execution_id"], headers)

    assert data["status"] == "success", data.get("error")
    assert len(fake.calls) == 1
    method, url, kwargs = fake.calls[0]
    assert url == "https://api.example.test/endpoint"
    assert kwargs["headers"]["Authorization"] == "Bearer S3CR3T-TOKEN-XYZ"


def test_secret_never_appears_in_execution_record(client):
    headers, ws_id = _setup_ws(client, "envexec2@test.com")
    _create_env(client, headers, ws_id, "API_URL", "https://api.example.test/secret-check")
    _create_env(client, headers, ws_id, "API_TOKEN", "TOPSECRET-VALUE-9Q8Z", secret=True)

    wf = {
        "id": "wf_env_secret",
        "name": "Env secret workflow",
        "workspace_id": ws_id,
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "call",
                "type": "http_request",
                "parameters": {
                    "url": "{{ $env.API_URL }}",
                    "headers": {"Authorization": "Bearer {{ $env.API_TOKEN }}"},
                },
            },
        ],
        "connections": [{"source": "trigger", "target": "call"}],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    fake = RecordingHTTPClient()
    with patch("app.execution_runtime._http_client", return_value=fake):
        run = client.post("/api/workflows/wf_env_secret/run", json={}, headers=headers).json()["data"]
        data = _poll(client, run["execution_id"], headers)

    assert data["status"] == "success"
    raw = str(data)
    assert "TOPSECRET-VALUE-9Q8Z" not in raw


def test_missing_env_var_stays_unresolved(client):
    """Unresolvable $env refs stay visible (same contract as $json)."""
    from app.engine.expressions import build_context, resolve

    ctx = build_context([{}], {}, "wf", "exec", None, {})
    assert resolve("{{ $env.NOPE }}", ctx) == "{{ $env.NOPE }}"
    ctx2 = build_context([{}], {}, "wf", "exec", None, {"KEY": "val"})
    assert resolve("{{ $env.KEY }}", ctx2) == "val"


def test_workspace_required_for_env_scoping(client):
    """A workflow without a workspace simply has no $env entries."""
    from app.engine.expressions import build_context, resolve

    ctx = build_context([{"a": 1}], {}, "wf", "exec", None, None)
    assert ctx["$env"] == {}
    assert resolve("{{ $json.a }}", ctx) == 1


def test_env_values_encrypted_at_rest(client):
    """Stored values must not be plaintext (spec 12/29)."""
    from app.db import get_session
    from app.models import Environment

    headers, ws_id = _setup_ws(client, "envexec3@test.com")
    _create_env(client, headers, ws_id, "PLAIN", "plain-value-abc")
    _create_env(client, headers, ws_id, "SECRET", "super-secret-value-xyz", secret=True)

    db = get_session()
    try:
        rows = db.query(Environment).filter_by(workspace_id=ws_id).all()
        by_key = {r.key: r.value for r in rows}
        assert by_key["PLAIN"] != "plain-value-abc"
        assert by_key["SECRET"] != "super-secret-value-xyz"
        assert by_key["PLAIN"].startswith("k")  # Fernet token prefix
    finally:
        db.close()

    # Non-secret values decrypt for workspace members via the API.
    body = client.get(f"/api/environments/{ws_id}", headers=headers).json()["data"]
    values = {e["key"]: e["value"] for e in body}
    assert values["PLAIN"] == "plain-value-abc"
    assert values["SECRET"].startswith("***")


def test_tenant_isolation_on_env_list(client):
    """Users outside the workspace cannot read its environment vars."""
    owner_headers, ws_id = _setup_ws(client, "envowner@test.com")
    _create_env(client, owner_headers, ws_id, "K", "v")

    outsider = auth_headers(register(client, email="outsider@test.com")["token"])
    resp = client.get(f"/api/environments/{ws_id}", headers=outsider)
    assert resp.status_code in (403, 404)


def test_non_owner_cannot_write_env(client):
    """Only the workspace creator manages environment variables."""
    owner_headers, ws_id = _setup_ws(client, "envowner2@test.com")

    member_data = register(client, email="envmember@test.com")
    member_headers = auth_headers(member_data["token"])
    # Add member to workspace so read access would be granted
    client.post(
        f"/api/workspaces/{ws_id}/members",
        json={"user_id": member_data["user"]["id"], "role": "member"},
        headers=owner_headers,
    )

    resp = client.post(
        "/api/environments",
        json={"workspace_id": ws_id, "key": "K", "value": "v"},
        headers=member_headers,
    )
    assert resp.status_code == 403
