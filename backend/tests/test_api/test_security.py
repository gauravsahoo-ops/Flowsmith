"""Security & access tests (security phase): login throttling, webhook
rate limits, roles, workflow sharing + enforcement, audit log, credential
key rotation."""

from __future__ import annotations

import pytest

from tests.test_api.conftest import auth_headers, make_workflow, register


@pytest.fixture(autouse=True)
def reset_global_throttles():
    """The login/webhook throttles are process-global in-memory stores;
    reset them so a locked key can't leak into other tests."""
    from app.api.auth import login_throttle
    from app.api.webhooks import _limiter

    login_throttle.reset()
    _limiter.reset()
    yield
    login_throttle.reset()
    _limiter.reset()


def test_login_throttled_after_failures(client):
    data = register(client)
    email = data["user"]["email"]
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": email, "password": "wrong"}).status_code == 401
    resp = client.post("/api/auth/login", json={"email": email, "password": "wrong"})
    assert resp.status_code == 429
    assert any(k.lower() == "retry-after" for k in resp.headers)
    resp = client.post("/api/auth/login", json={"email": email, "password": "Password123!"})
    assert resp.status_code == 429


def test_login_not_throttled_by_successes(client):
    data = register(client)
    email = data["user"]["email"]
    for _ in range(10):
        resp = client.post("/api/auth/login", json={"email": email, "password": "Password123!"})
        assert resp.status_code == 200


def test_webhook_rate_limited_per_path(client):
    reg = register(client)
    wf = make_workflow("wf_hook")
    wf["nodes"] = [{"id": "webhook", "type": "webhook", "parameters": {"method": "POST", "path": "rate-test-webhook-path-0123456789abcdef"}}]
    wf["connections"] = []
    assert client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"])).status_code == 201
    assert (
        client.patch(f"/api/workflows/{wf['id']}/active", json={"active": True}, headers=auth_headers(reg["token"])).status_code
        == 200
    )
    for _ in range(60):
        assert client.post("/api/webhooks/rate-test-webhook-path-0123456789abcdef", json={}).status_code == 202
    resp = client.post("/api/webhooks/rate-test-webhook-path-0123456789abcdef", json={})
    assert resp.status_code == 429
    assert any(k.lower() == "retry-after" for k in resp.headers)
    # a different path is unaffected
    assert client.post("/api/webhooks/rate-test-other", json={}).status_code == 404


def test_first_user_is_admin_second_is_member(client):
    admin = register(client, "admin@x.com")
    member = register(client, "member@x.com")
    assert admin["user"]["role"] == "admin"
    assert member["user"]["role"] == "member"
    assert client.get("/api/users", headers=auth_headers(member["token"])).status_code == 403
    resp = client.get("/api/users", headers=auth_headers(admin["token"]))
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 2


def test_last_admin_cannot_be_demoted_or_deactivated(client):
    admin = register(client, "admin@x.com")
    uid = admin["user"]["id"]
    assert client.patch(f"/api/users/{uid}", json={"role": "member"}, headers=auth_headers(admin["token"])).status_code == 422
    assert client.patch(f"/api/users/{uid}", json={"active": False}, headers=auth_headers(admin["token"])).status_code == 422


def test_admin_promotes_and_deactivates_member(client):
    admin = register(client, "admin@x.com")
    member = register(client, "member@x.com")
    bid = member["user"]["id"]
    resp = client.patch(f"/api/users/{bid}", json={"role": "admin"}, headers=auth_headers(admin["token"]))
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "admin"
    resp = client.patch(f"/api/users/{bid}", json={"active": False}, headers=auth_headers(admin["token"]))
    assert resp.status_code == 200
    assert resp.json()["data"]["active"] is False
    assert client.post("/api/auth/login", json={"email": "member@x.com", "password": "Password123!"}).status_code == 401
    assert client.get("/api/workflows", headers=auth_headers(member["token"])).status_code == 401


def test_shared_workflow_view_edit_lifecycle(client):
    owner = register(client, "owner@x.com")
    viewer = register(client, "viewer@x.com")
    wf = make_workflow()
    resp = client.post("/api/workflows", json=wf, headers=auth_headers(owner["token"]))
    assert resp.status_code == 201
    wid = resp.json()["data"]["id"]

    assert client.get(f"/api/workflows/{wid}", headers=auth_headers(viewer["token"])).status_code == 404
    assert client.get("/api/workflows", headers=auth_headers(viewer["token"])).json()["data"] == []
    assert client.post(f"/api/workflows/{wid}/run", json={}, headers=auth_headers(viewer["token"])).status_code == 404
    assert client.put(f"/api/workflows/{wid}", json=wf, headers=auth_headers(viewer["token"])).status_code == 404
    assert client.patch(f"/api/workflows/{wid}/active", json={"active": True}, headers=auth_headers(viewer["token"])).status_code == 404
    assert client.delete(f"/api/workflows/{wid}", headers=auth_headers(viewer["token"])).status_code == 404

    resp = client.post(
        f"/api/workflows/{wid}/shares",
        json={"email": "viewer@x.com", "permission": "view"},
        headers=auth_headers(owner["token"]),
    )
    assert resp.status_code == 201
    assert client.get(f"/api/workflows/{wid}", headers=auth_headers(viewer["token"])).status_code == 200
    listed = client.get("/api/workflows", headers=auth_headers(viewer["token"])).json()["data"]
    assert len(listed) == 1 and listed[0]["id"] == wid and listed[0]["permission"] == "view"
    assert client.put(f"/api/workflows/{wid}", json=wf, headers=auth_headers(viewer["token"])).status_code == 404

    resp = client.patch(
        f"/api/workflows/{wid}/shares/{viewer['user']['id']}",
        json={"permission": "edit"},
        headers=auth_headers(owner["token"]),
    )
    assert resp.status_code == 200
    assert client.put(f"/api/workflows/{wid}", json=wf, headers=auth_headers(viewer["token"])).status_code == 200
    assert client.post(f"/api/workflows/{wid}/run", json={}, headers=auth_headers(viewer["token"])).status_code == 202
    assert client.delete(f"/api/workflows/{wid}", headers=auth_headers(viewer["token"])).status_code == 404
    assert client.delete(f"/api/workflows/{wid}/shares/{owner['user']['id']}", headers=auth_headers(viewer["token"])).status_code == 404

    assert client.delete(f"/api/workflows/{wid}/shares/{viewer['user']['id']}", headers=auth_headers(owner["token"])).status_code == 204
    assert client.get(f"/api/workflows/{wid}", headers=auth_headers(viewer["token"])).status_code == 404


def test_owner_cannot_share_with_self_or_unknown_email(client):
    owner = register(client, "owner@x.com")
    wf = make_workflow()
    client.post("/api/workflows", json=wf, headers=auth_headers(owner["token"]))
    resp = client.post(
        f"/api/workflows/{wf['id']}/shares",
        json={"email": "owner@x.com", "permission": "edit"},
        headers=auth_headers(owner["token"]),
    )
    assert resp.status_code == 422
    resp = client.post(
        f"/api/workflows/{wf['id']}/shares",
        json={"email": "ghost@x.com", "permission": "edit"},
        headers=auth_headers(owner["token"]),
    )
    assert resp.status_code == 404


def test_shared_executions_visible_to_viewer(client):
    owner = register(client, "owner@x.com")
    viewer = register(client, "viewer@x.com")
    wf = make_workflow()
    resp = client.post("/api/workflows", json=wf, headers=auth_headers(owner["token"]))
    wid = resp.json()["data"]["id"]
    run = client.post(f"/api/workflows/{wid}/run", json={}, headers=auth_headers(owner["token"]))
    assert run.status_code == 202
    exec_id = run.json()["data"]["execution_id"]
    assert client.get(f"/api/executions/{exec_id}", headers=auth_headers(viewer["token"])).status_code == 404

    client.post(f"/api/workflows/{wid}/shares", json={"email": "viewer@x.com", "permission": "view"}, headers=auth_headers(owner["token"]))
    detail = client.get(f"/api/executions/{exec_id}", headers=auth_headers(viewer["token"]))
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == exec_id
    listed = client.get(f"/api/executions?workflow_id={wid}", headers=auth_headers(viewer["token"])).json()["data"]
    assert any(e["id"] == exec_id for e in listed)
    # viewer cannot retry/cancel (edit-only)
    assert client.post(f"/api/executions/{exec_id}/retry", headers=auth_headers(viewer["token"])).status_code == 404
    # owner can retry
    assert client.post(f"/api/executions/{exec_id}/retry", headers=auth_headers(owner["token"])).status_code == 202


def test_audit_log_records_and_requires_admin(client):
    admin = register(client, "admin@x.com")
    member = register(client, "member@x.com")
    assert client.get("/api/audit", headers=auth_headers(member["token"])).status_code == 403
    resp = client.get("/api/audit", headers=auth_headers(admin["token"]))
    assert resp.status_code == 200
    actions = {e["action"] for e in resp.json()["data"]}
    assert "auth.register" in actions
    assert "auth.login" in actions
    resp = client.get("/api/audit?action=auth.login", headers=auth_headers(admin["token"]))
    assert resp.status_code == 200
    assert resp.json()["data"]
    assert all(e["action"] == "auth.login" for e in resp.json()["data"])


def test_workflow_actions_are_audited(client):
    admin = register(client, "admin@x.com")
    wf = make_workflow()
    client.post("/api/workflows", json=wf, headers=auth_headers(admin["token"]))
    client.patch(f"/api/workflows/{wf['id']}/active", json={"active": True}, headers=auth_headers(admin["token"]))
    client.delete(f"/api/workflows/{wf['id']}", headers=auth_headers(admin["token"]))
    resp = client.get("/api/audit", headers=auth_headers(admin["token"]))
    actions = {e["action"] for e in resp.json()["data"]}
    assert {"workflow.create", "workflow.activate", "workflow.delete"} <= actions


def test_crypto_key_rotation(client):
    from cryptography.fernet import Fernet

    from app.config import get_settings
    from app.security import crypto

    settings = get_settings()
    key_a, key_b = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings.credentials_encryption_key = key_a
    try:
        token = crypto.encrypt_text('{"api_key":"s3cret"}')
        assert crypto.decrypt_text(token) == '{"api_key":"s3cret"}'

        settings.credentials_encryption_key = f"{key_b},{key_a}"
        assert crypto.decrypt_text(token) == '{"api_key":"s3cret"}'
        new_token = crypto.encrypt_text('{"api_key":"other"}')
        assert new_token.decode().startswith("k0:")
        assert crypto.decrypt_text(new_token) == '{"api_key":"other"}'

        settings.credentials_encryption_key = key_b
        with pytest.raises(crypto.CredentialDecryptionError):
            crypto.decrypt_text(token)
        assert crypto.decrypt_text(new_token) == '{"api_key":"other"}'

        settings.credentials_encryption_key = key_a
        legacy = Fernet(key_a.encode()).encrypt(b'{"api_key":"legacy"}')
        assert crypto.decrypt_text(legacy) == '{"api_key":"legacy"}'
    finally:
        settings.credentials_encryption_key = ""


def test_reencrypt_all_rotates_stored_credentials(client):
    from cryptography.fernet import Fernet

    from app.config import get_settings
    from app.db import get_session
    from app.credentials import service
    from app.models import Credential

    settings = get_settings()
    key_a, key_b = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings.credentials_encryption_key = key_a
    reg = register(client)
    resp = client.post(
        "/api/credentials",
        json={"name": "myhttp", "type": "http", "data": {"api_key": "v"}},
        headers=auth_headers(reg["token"]),
    )
    assert resp.status_code == 201
    cred_id = resp.json()["data"]["id"]
    settings.credentials_encryption_key = f"{key_b},{key_a}"
    db = get_session()
    try:
        assert service.reencrypt_all(db) == 1
        rec = db.get(Credential, cred_id)
        assert rec is not None
        assert rec.data.decode().startswith("k0:")
    finally:
        db.close()
    settings.credentials_encryption_key = key_b
    db = get_session()
    try:
        resolved = service.resolve_credentials(db, reg["user"]["id"], {"http": cred_id})
        assert resolved["http"]["api_key"] == "v"
    finally:
        db.close()
    settings.credentials_encryption_key = ""
