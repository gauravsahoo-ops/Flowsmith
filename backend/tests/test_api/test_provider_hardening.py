"""Security regressions for provider registration, replay, and cleanup."""

from __future__ import annotations

import hashlib
import hmac

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import ProviderWebhookRegistration
from app.security.crypto import decrypt_text
from tests.test_api.conftest import auth_headers, register
from tests.test_api.test_provider_webhook_registration import (
    FakeClient,
    FakeResponse,
    _setup,
)


def _github_setup(client, monkeypatch, fake):
    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client", lambda: fake
    )
    monkeypatch.setattr(get_settings(), "public_url", "https://flowsmith.test")
    path = "github-hardening-path-1234567890"
    _, headers, credential = _setup(
        client,
        node_type="github_trigger",
        path=path,
        credential_type="github",
        credential_data={"access_token": "ghp_test"},
    )
    return path, headers, credential


def test_typeform_path_segments_are_rejected(client, monkeypatch):
    fake = FakeClient([FakeResponse(200, {"ok": True})])
    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client", lambda: fake
    )
    monkeypatch.setattr(get_settings(), "public_url", "https://flowsmith.test")
    path = "typeform-hardening-path-1234567890"
    _, headers, credential = _setup(
        client,
        node_type="typeform_trigger",
        path=path,
        credential_type="typeform",
        credential_data={"token": "tf_test"},
    )
    response = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "signing_secret": "probe-secret",
            "config": {"form_id": "../../victim", "tag": "../../victim-hook"},
        },
        headers=headers,
    )
    assert response.status_code == 400, response.text
    assert "form_id" in response.json()["detail"].lower()
    assert fake.calls == []


def test_duplicate_github_delivery_is_deduplicated(client, monkeypatch):
    fake = FakeClient([FakeResponse(201, {"id": 123})])
    path, headers, credential = _github_setup(client, monkeypatch, fake)
    registered = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {"repository": "acme/repo", "events": ["push"]},
        },
        headers=headers,
    )
    assert registered.status_code == 200, registered.text

    db = get_session()
    try:
        row = db.scalar(
            select(ProviderWebhookRegistration).where(
                ProviderWebhookRegistration.workflow_id == f"wf_{path}"
            )
        )
        assert row is not None
        secret = decrypt_text(row.signing_secret)
    finally:
        db.close()

    payload = b'{"action":"opened"}'
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    delivery_headers = {
        "x-hub-signature-256": f"sha256={signature}",
        "x-github-delivery": "same-provider-delivery-id",
    }
    first = client.post(f"/api/webhooks/{path}", content=payload, headers=delivery_headers)
    second = client.post(f"/api/webhooks/{path}", content=payload, headers=delivery_headers)
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert second.json()["data"]["replayed"] is True
    assert second.json()["data"]["delivery_id"] == first.json()["data"]["delivery_id"]


def test_provider_error_body_is_not_echoed(client, monkeypatch):
    fake = FakeClient([FakeResponse(500, {"error": "TOPSECRET-MUST-NOT-LEAK"})])
    path, headers, credential = _github_setup(client, monkeypatch, fake)
    response = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {"repository": "acme/repo"},
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "TOPSECRET-MUST-NOT-LEAK" not in response.text
    assert "HTTP 500" in response.json()["detail"]


def test_force_unregister_queues_cleanup_instead_of_orphaning(client, monkeypatch):
    fake = FakeClient([
        FakeResponse(201, {"id": 456}),
        FakeResponse(500, {"error": "provider unavailable"}),
        FakeResponse(204),
    ])
    path, headers, credential = _github_setup(client, monkeypatch, fake)
    registered = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {"repository": "acme/repo"},
        },
        headers=headers,
    )
    assert registered.status_code == 200, registered.text
    reg_id = registered.json()["data"]["id"]

    forced = client.delete(f"/api/provider-webhooks/{reg_id}?force=true", headers=headers)
    assert forced.status_code == 200, forced.text
    assert forced.json()["data"]["cleanup_pending"] is True
    assert forced.json()["data"]["unregistered"] is False

    db = get_session()
    try:
        row = db.get(ProviderWebhookRegistration, reg_id)
        assert row is not None
        assert row.status == "orphaned"
        assert "provider unavailable" not in (row.last_error or "")
    finally:
        db.close()

    import asyncio
    from app.services.provider_webhook_reaper import reap_provider_webhooks

    assert asyncio.run(reap_provider_webhooks()) == 1
    db = get_session()
    try:
        assert db.get(ProviderWebhookRegistration, reg_id) is None
    finally:
        db.close()


def test_provider_last_error_is_hidden_from_viewers(client, monkeypatch):
    fake = FakeClient([
        FakeResponse(201, {"id": 222}),
        FakeResponse(500, {"error": "provider secret detail"}),
    ])
    path, headers, credential = _github_setup(client, monkeypatch, fake)
    owner = client.get("/api/auth/me", headers=headers)
    assert owner.status_code == 200
    viewer = register(client, "provider-viewer@example.com")
    shared = client.post(
        f"/api/workflows/wf_{path}/shares",
        json={"email": viewer["user"]["email"], "permission": "view"},
        headers=headers,
    )
    assert shared.status_code == 201, shared.text

    registered = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {"repository": "acme/repo"},
        },
        headers=headers,
    )
    assert registered.status_code == 200, registered.text
    reg_id = registered.json()["data"]["id"]

    failed = client.delete(f"/api/provider-webhooks/{reg_id}", headers=headers)
    assert failed.status_code == 502
    assert "provider secret detail" not in failed.text

    listed = client.get(
        f"/api/provider-webhooks?workflow_id=wf_{path}",
        headers=auth_headers(viewer["token"]),
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"][0]["last_error"] is None


def test_provider_config_is_bounded(client, monkeypatch):
    fake = FakeClient([FakeResponse(201, {"id": 789})])
    path, headers, credential = _github_setup(client, monkeypatch, fake)
    too_many_events = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {"repository": "acme/repo", "events": [f"event-{i}" for i in range(51)]},
        },
        headers=headers,
    )
    assert too_many_events.status_code == 400
    assert "events" in too_many_events.json()["detail"].lower()

    too_many_keys = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {
                "repository": "acme/repo",
                **{f"extra_{i}": "x" for i in range(40)},
            },
        },
        headers=headers,
    )
    assert too_many_keys.status_code == 400
    assert "config" in too_many_keys.json()["detail"].lower()
    assert fake.calls == []
