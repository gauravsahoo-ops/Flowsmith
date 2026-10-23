"""Regression tests for the 2026-10-22 production-readiness audit.

Each test maps to a specific finding so the fix cannot silently regress.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import (
    Environment,
    Organization,
    OrganizationMember,
    Subscription,
    User,
    Workspace,
    WorkspaceMember,
)
from tests.test_api.conftest import auth_headers, make_workflow, register


def _unique_email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}@test.com"


def _create_workflow(client: TestClient, headers: dict, wf_id: str) -> dict:
    resp = client.post("/api/workflows", json=make_workflow(wf_id), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# H-6 / M-1: registration policy and bootstrap
# ---------------------------------------------------------------------------


def test_registration_closed_after_bootstrap(client: TestClient, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "registration_mode", "closed")

    first = register(client, email=_unique_email("bootstrap"))
    assert first["user"]["role"] == "admin"

    resp = client.post(
        "/api/auth/register",
        json={"email": _unique_email("blocked"), "password": "Password123!"},
    )
    assert resp.status_code == 403, resp.text


def test_registration_invite_requires_matching_code(client: TestClient, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "registration_mode", "invite")
    monkeypatch.setattr(settings, "registration_invite_code", "s3cret-invite-code-123")

    register(client, email=_unique_email("invite_bootstrap"))

    missing = client.post(
        "/api/auth/register",
        json={"email": _unique_email("invite_missing"), "password": "Password123!"},
    )
    assert missing.status_code == 403

    wrong = client.post(
        "/api/auth/register",
        json={
            "email": _unique_email("invite_wrong"),
            "password": "Password123!",
            "invite_code": "not-the-code",
        },
    )
    assert wrong.status_code == 403

    accepted = client.post(
        "/api/auth/register",
        json={
            "email": _unique_email("invite_ok"),
            "password": "Password123!",
            "invite_code": "s3cret-invite-code-123",
        },
    )
    assert accepted.status_code == 201, accepted.text


def test_first_admin_requires_out_of_band_bootstrap_token(client: TestClient, monkeypatch):
    token = "b" * 40
    monkeypatch.setattr(get_settings(), "registration_bootstrap_token", token)

    denied = client.post(
        "/api/auth/register",
        json={"email": _unique_email("bootstrap_denied"), "password": "Password123!"},
    )
    assert denied.status_code == 403, denied.text

    accepted = client.post(
        "/api/auth/register",
        json={
            "email": _unique_email("bootstrap_ok"),
            "password": "Password123!",
            "bootstrap_token": token,
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["data"]["user"]["role"] == "admin"


# ---------------------------------------------------------------------------
# H-7: private workspaces are member-only
# ---------------------------------------------------------------------------


def test_private_workspace_hidden_from_org_member(client: TestClient):
    owner = register(client, email=_unique_email("ws_owner"))
    member = register(client, email=_unique_email("ws_member"))
    owner_headers = auth_headers(owner["token"])
    member_headers = auth_headers(member["token"])

    org_id = client.post(
        "/api/organizations", json={"name": f"Private Org {uuid.uuid4().hex[:6]}"},
        headers=owner_headers,
    ).json()["data"]["id"]
    ws_id = client.post(
        "/api/workspaces",
        json={"name": "Secret WS", "organization_id": org_id, "is_private": True},
        headers=owner_headers,
    ).json()["data"]["id"]
    assert client.post(
        f"/api/organizations/{org_id}/members",
        json={"user_id": member["user"]["id"], "role": "member"},
        headers=owner_headers,
    ).status_code == 200

    assert client.get(f"/api/workspaces/{ws_id}", headers=member_headers).status_code == 404
    listed = client.get("/api/workspaces", headers=member_headers).json()["data"]
    assert ws_id not in {w["id"] for w in listed}

    # A view-only org member must not be able to attach a workflow and read
    # the workspace environment.
    wf = make_workflow(f"wf_{uuid.uuid4().hex[:8]}")
    wf["workspace_id"] = ws_id
    denied = client.post("/api/workflows", json=wf, headers=member_headers)
    assert denied.status_code == 403, denied.text


# ---------------------------------------------------------------------------
# C-1: duplicate requires edit, and never clones a foreign workspace
# ---------------------------------------------------------------------------


def test_duplicate_requires_edit_permission(client: TestClient):
    owner = register(client, email=_unique_email("dup_owner"))
    viewer = register(client, email=_unique_email("dup_viewer"))
    owner_headers = auth_headers(owner["token"])
    viewer_headers = auth_headers(viewer["token"])

    wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    _create_workflow(client, owner_headers, wf_id)
    share = client.post(
        f"/api/workflows/{wf_id}/shares",
        json={"email": viewer["user"]["email"], "permission": "view"},
        headers=owner_headers,
    )
    assert share.status_code == 201, share.text

    resp = client.post(f"/api/workflows/{wf_id}/duplicate", headers=viewer_headers)
    assert resp.status_code == 404, resp.text


def test_shared_user_cannot_read_workspace_environment():
    """The runtime refuses workspace env vars to a non-member executor."""
    from app.execution_runtime import _resolve_env_vars
    from app.queue import QueueJob

    db = get_session()
    try:
        owner = User(email=_unique_email("env_owner"), password_hash="x")
        outsider = User(email=_unique_email("env_outsider"), password_hash="x")
        db.add_all([owner, outsider])
        db.flush()
        org = Organization(
            id=f"org_{uuid.uuid4().hex[:8]}", name=_unique_email("env_org"),
            founder_id=owner.id,
        )
        db.add(org)
        db.flush()
        ws = Workspace(
            id=f"ws_{uuid.uuid4().hex[:8]}", name="Env WS", organization_id=org.id,
            creator_id=owner.id, is_private=True,
        )
        db.add(ws)
        db.flush()
        db.add(Environment(workspace_id=ws.id, key="API_TOKEN", value="encrypted", is_secret=True))
        db.commit()

        job = QueueJob(
            id="job_env",
            execution_id="exec_env",
            payload={
                "user_id": outsider.id,
                "workspace_id": ws.id,
                "workflow_id": "wf_env",
                "workflow_data": {},
                "trigger_items": [],
                "trigger": "manual",
            },
        )
        assert _resolve_env_vars(db, job) == {}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# M-7: checkout URL origin and organization cleanup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,base,expected",
    [
        ("", "https://app.example.com", "https://app.example.com/?billing=success"),
        ("/done", "https://app.example.com", "https://app.example.com/done"),
        ("https://app.example.com/done", "https://app.example.com", "https://app.example.com/done"),
    ],
)
def test_billing_return_url_allowed(value, base, expected):
    from app.api.billing import _safe_return_url

    assert _safe_return_url(value, base=base, default_path="/?billing=success") == expected


@pytest.mark.parametrize(
    "value", ["https://evil.example/phish", "//evil.example/phish", "javascript:alert(1)"]
)
def test_billing_return_url_rejects_foreign_origin(value):
    from fastapi import HTTPException

    from app.api.billing import _safe_return_url

    with pytest.raises(HTTPException) as exc:
        _safe_return_url(value, base="https://app.example.com", default_path="/?billing=success")
    assert exc.value.status_code in (400, 503)


def test_organization_delete_cleans_empty_workspaces(client: TestClient):
    owner = register(client, email=_unique_email("orgdel"))
    headers = auth_headers(owner["token"])
    org_id = client.post(
        "/api/organizations", json={"name": f"Delete Org {uuid.uuid4().hex[:6]}"},
        headers=headers,
    ).json()["data"]["id"]
    ws_id = client.post(
        "/api/workspaces", json={"name": "Empty WS", "organization_id": org_id},
        headers=headers,
    ).json()["data"]["id"]

    db = get_session()
    try:
        db.add(Subscription(organization_id=org_id, plan="free"))
        db.commit()
    finally:
        db.close()

    resp = client.delete(f"/api/organizations/{org_id}", headers=headers)
    assert resp.status_code == 200, resp.text

    db = get_session()
    try:
        assert db.get(Workspace, ws_id) is None
        assert db.get(Organization, org_id) is None
        assert db.scalar(select(Subscription).where(Subscription.organization_id == org_id)) is None
        assert db.scalar(
            select(OrganizationMember).where(OrganizationMember.organization_id == org_id)
        ) is None
        assert db.scalar(
            select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id)
        ) is None
    finally:
        db.close()


def test_organization_delete_refuses_when_workflows_remain(client: TestClient):
    owner = register(client, email=_unique_email("orgwf"))
    headers = auth_headers(owner["token"])
    org_id = client.post(
        "/api/organizations", json={"name": f"WF Org {uuid.uuid4().hex[:6]}"},
        headers=headers,
    ).json()["data"]["id"]
    ws_id = client.post(
        "/api/workspaces", json={"name": "Busy WS", "organization_id": org_id},
        headers=headers,
    ).json()["data"]["id"]

    wf = make_workflow(f"wf_{uuid.uuid4().hex[:8]}")
    wf["workspace_id"] = ws_id
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    resp = client.delete(f"/api/organizations/{org_id}", headers=headers)
    assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------------
# M-7: private workspace access through the shared parity rules
# ---------------------------------------------------------------------------


def test_workspace_editor_can_manage_environment(client: TestClient):
    owner = register(client, email=_unique_email("env_owner_ws"))
    editor = register(client, email=_unique_email("env_editor_ws"))
    owner_headers = auth_headers(owner["token"])
    editor_headers = auth_headers(editor["token"])

    org_id = client.post(
        "/api/organizations", json={"name": f"Env Org {uuid.uuid4().hex[:6]}"},
        headers=owner_headers,
    ).json()["data"]["id"]
    ws_id = client.post(
        "/api/workspaces", json={"name": "Env WS", "organization_id": org_id},
        headers=owner_headers,
    ).json()["data"]["id"]
    added = client.post(
        f"/api/workspaces/{ws_id}/members",
        json={"user_id": editor["user"]["id"], "role": "editor"},
        headers=owner_headers,
    )
    assert added.status_code == 200, added.text

    created = client.post(
        "/api/environments",
        json={"workspace_id": ws_id, "key": "API_URL", "value": "https://example.test", "is_secret": False},
        headers=editor_headers,
    )
    assert created.status_code == 200, created.text
    env_id = created.json()["data"]["id"]

    deleted = client.delete(f"/api/environments/{env_id}", headers=editor_headers)
    assert deleted.status_code == 200, deleted.text


def test_private_workspace_creator_and_explicit_member():
    from app.api.access import workspace_can_view

    db = get_session()
    try:
        owner = User(email=_unique_email("priv_owner"), password_hash="x")
        member = User(email=_unique_email("priv_member"), password_hash="x")
        db.add_all([owner, member])
        db.flush()
        org = Organization(
            id=f"org_{uuid.uuid4().hex[:8]}", name=_unique_email("priv_org"),
            founder_id=owner.id,
        )
        db.add(org)
        db.flush()
        ws = Workspace(
            id=f"ws_{uuid.uuid4().hex[:8]}", name="Private", organization_id=org.id,
            creator_id=owner.id, is_private=True,
        )
        db.add(ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=member.id, role="member", permission="view"))
        db.commit()

        assert workspace_can_view(db, ws.id, owner.id) is True
        assert workspace_can_view(db, ws.id, member.id) is True
    finally:
        db.close()


# ---------------------------------------------------------------------------
# H-4: code node source cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_node_rejects_oversized_source():
    from app.engine.errors import NodeExecutionError
    from app.nodes.code import MAX_CODE_CHARS, CodeNode, CodeParams

    node = CodeNode()
    params = CodeParams(code="x" * (MAX_CODE_CHARS + 1), language="python")
    with pytest.raises(NodeExecutionError) as exc:
        await node.run(MagicMock(), params, [{}])
    assert exc.value.code == "CODE_TOO_LARGE"


@pytest.mark.asyncio
async def test_code_node_bounds_per_item_execution():
    from app.engine.errors import NodeExecutionError
    from app.nodes.code import MAX_PER_ITEM_INPUTS, CodeNode, CodeParams

    node = CodeNode()
    params = CodeParams(code="return $input.item", language="javascript", mode="runOnceForEachItem")
    with pytest.raises(NodeExecutionError) as exc:
        await node.run(MagicMock(), params, [{}] * (MAX_PER_ITEM_INPUTS + 1))
    assert exc.value.code == "TOO_MANY_ITEMS"


def test_served_spa_index_gets_csp_nonce(client: TestClient):
    """The built UI must not rely on style-src 'unsafe-inline'."""
    from app.main import FRONTEND_DIST

    if FRONTEND_DIST is None or not (FRONTEND_DIST / "index.html").is_file():
        pytest.skip("frontend dist not built")
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'name="csp-nonce"' in resp.text
    csp = resp.headers.get("content-security-policy", "")
    assert "style-src 'self' 'nonce-" in csp
    assert "style-src-attr 'unsafe-inline'" in csp


# ---------------------------------------------------------------------------
# M-3: per-item retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_path_retries_each_item():
    from app.engine.errors import NodeExecutionError
    from app.engine.executor import execute_workflow
    from app.engine.node_base import BaseNode, EmptyParams, NodeContext, NodeResult
    from app.nodes.registry import NODE_REGISTRY, register
    from tests.conftest import conn, make_node, make_workflow

    flaky_type = "flaky_batch_regression"
    attempts = {"count": 0}

    @register
    class FlakyBatchNode(BaseNode[EmptyParams]):
        node_type = flaky_type
        display_name = "Flaky batch (test)"
        version = 1
        input_handles = ["main"]
        output_handles = ["main"]

        async def run(
            self, ctx: NodeContext, params: EmptyParams, input_items: list[dict]
        ) -> NodeResult:
            attempts["count"] += 1
            # Fail each item's first attempt once, then succeed.
            if attempts["count"] % 2 == 1:
                raise NodeExecutionError("transient", retryable=True)
            return NodeResult(output_items=[{"ok": True}])

    try:
        wf = make_workflow(
            [
                make_node("trigger", "manual_trigger"),
                make_node("A", "set_data", parameters={"fields": {"data": [{"i": 1}, {"i": 2}]}}),
                make_node("split", "split", parameters={"field": "data"}),
                make_node(
                    flaky_type,
                    flaky_type,
                    settings={"retry_max_attempts": 1, "retry_backoff_seconds": 0},
                ),
            ],
            [conn("trigger", "A"), conn("A", "split"), conn("split", flaky_type)],
        )
        result = await execute_workflow(wf, [{"start": True}])
    finally:
        NODE_REGISTRY.pop(flaky_type, None)

    assert result.status == "success"
    assert attempts["count"] == 4  # 2 items x (fail once + succeed)
    assert len(result.results[flaky_type]["main"]) == 2


# ---------------------------------------------------------------------------
# M-1: trusted proxy handling
# ---------------------------------------------------------------------------


def _request(peer: str, forwarded: str | None = None):
    from starlette.requests import Request

    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("testserver", 80),
        }
    )


def test_forwarded_header_ignored_from_untrusted_peer(monkeypatch):
    from app.security import client_ip

    settings = get_settings()
    monkeypatch.setattr(settings, "trusted_proxies", "127.0.0.1")
    client_ip._trusted_networks.cache_clear()
    try:
        assert client_ip.client_ip(_request("203.0.113.9", "198.51.100.7")) == "203.0.113.9"
    finally:
        client_ip._trusted_networks.cache_clear()


def test_forwarded_header_used_from_trusted_proxy(monkeypatch):
    from app.security import client_ip

    settings = get_settings()
    monkeypatch.setattr(settings, "trusted_proxies", "127.0.0.1,10.0.0.0/8")
    client_ip._trusted_networks.cache_clear()
    try:
        req = _request("127.0.0.1", "198.51.100.7, 10.1.2.3")
        assert client_ip.client_ip(req) == "198.51.100.7"
    finally:
        client_ip._trusted_networks.cache_clear()


# ---------------------------------------------------------------------------
# M-4: stateless SSO state is signed and browser-bound
# ---------------------------------------------------------------------------


def test_sso_state_is_signed_and_bound_to_nonce():
    from fastapi import HTTPException

    from app.api.sso import _new_sso_state, _verify_sso_state

    state, nonce = _new_sso_state("github")
    _verify_sso_state(state, "github", nonce)

    with pytest.raises(HTTPException):
        _verify_sso_state(state, "github", "wrong-nonce")
    with pytest.raises(HTTPException):
        _verify_sso_state(state, "google", nonce)
    with pytest.raises(HTTPException):
        _verify_sso_state(state + "tampered", "github", nonce)


# ---------------------------------------------------------------------------
# H-2: deactivated users cannot log in through SSO
# ---------------------------------------------------------------------------


def test_sso_rejects_inactive_existing_user(monkeypatch):
    from app.api import sso
    from app.config import get_settings as sso_settings

    settings = sso_settings()
    email = _unique_email("sso_inactive")
    monkeypatch.setattr(settings, "sso_github_client_id", "gh-id")
    monkeypatch.setattr(settings, "sso_github_client_secret", "gh-secret")

    db = get_session()
    try:
        db.add(User(email=email, password_hash="x", active=False))
        db.commit()
    finally:
        db.close()

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            return _FakeResp({"access_token": "fake"})

        async def get(self, url, **kwargs):
            if "user/emails" in url:
                return _FakeResp([{"email": email, "primary": True, "verified": True}])
            return _FakeResp({"login": "inactive", "email": email})

    class _FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    monkeypatch.setattr(sso.httpx, "AsyncClient", _FakeAsyncClient)

    # Use the application client so the login cookie is carried to the callback.
    from app.main import app

    client = TestClient(app)
    try:
        login = client.get("/api/auth/sso/github/login", follow_redirects=False)
        assert login.status_code == 302, login.text
        from urllib.parse import parse_qs, urlparse

        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        callback = client.get(
            "/api/auth/sso/github/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )
        assert callback.status_code == 403, callback.text
    finally:
        client.close()
