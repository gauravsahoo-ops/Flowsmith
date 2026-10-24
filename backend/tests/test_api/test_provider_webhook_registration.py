"""Automatic provider-side webhook registration tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import ProviderWebhookRegistration
from app.security.crypto import decrypt_text
from tests.test_api.conftest import auth_headers, register


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def _take(self, method: str, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError(f"Unexpected {method} {url}")
        return self.responses.pop(0)

    async def request(self, method: str, url: str, **kwargs) -> FakeResponse:
        return await self._take(method, url, **kwargs)

    async def post(self, url: str, **kwargs) -> FakeResponse:
        return await self._take("POST", url, **kwargs)

    async def put(self, url: str, **kwargs) -> FakeResponse:
        return await self._take("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs) -> FakeResponse:
        return await self._take("DELETE", url, **kwargs)


def _setup(client, *, node_type: str, path: str, credential_type: str, credential_data: dict):
    user = register(client)
    headers = auth_headers(user["token"])
    credential = client.post(
        "/api/credentials",
        json={"name": "Provider test", "type": credential_type, "data": credential_data},
        headers=headers,
    )
    assert credential.status_code == 201, credential.text
    workflow = {
        "id": f"wf_{path}",
        "name": "Provider registration workflow",
        "nodes": [{
            "id": "trigger",
            "type": node_type,
            "parameters": {"path": path, "method": "POST"},
        }],
        "connections": [],
        "settings": {},
    }
    assert client.post("/api/workflows", json=workflow, headers=headers).status_code == 201
    assert client.patch(
        f"/api/workflows/wf_{path}/active", json={"active": True}, headers=headers
    ).status_code == 200
    return user, headers, credential.json()["data"]


def test_github_provider_registration_and_receiver_secret(client, monkeypatch):
    fake = FakeClient([
        FakeResponse(201, {"id": 123}),
        FakeResponse(204),
    ])
    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client", lambda: fake
    )
    monkeypatch.setattr(get_settings(), "public_url", "https://flowsmith.test")
    path = "github-provider-registration-123456"
    _, headers, credential = _setup(
        client,
        node_type="github_trigger",
        path=path,
        credential_type="github",
        credential_data={"access_token": "ghp_test"},
    )
    response = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {"repository": "acme/repo", "events": ["push"]},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["provider"] == "github"
    assert data["callback_url"] == f"https://flowsmith.test/api/webhooks/{path}"

    db = get_session()
    try:
        row = db.scalar(
            select(ProviderWebhookRegistration).where(
                ProviderWebhookRegistration.id == data["id"]
            )
        )
        assert row is not None
        secret = decrypt_text(row.signing_secret)
    finally:
        db.close()

    payload = b'{"action":"opened"}'
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    accepted = client.post(
        f"/api/webhooks/{path}",
        content=payload,
        headers={"x-hub-signature-256": f"sha256={signature}"},
    )
    assert accepted.status_code == 202, accepted.text

    removed = client.delete(f"/api/provider-webhooks/{data['id']}", headers=headers)
    assert removed.status_code == 200, removed.text
    assert fake.calls[0]["method"] == "POST"
    assert fake.calls[0]["json"]["config"]["url"] == f"https://flowsmith.test/api/webhooks/{path}"
    assert fake.calls[-1]["method"] == "DELETE"
    db = get_session()
    try:
        assert db.get(ProviderWebhookRegistration, data["id"]) is None
    finally:
        db.close()


def test_gitlab_provider_registration_and_receiver_token(client, monkeypatch):
    fake = FakeClient([
        FakeResponse(201, {"id": 42}),
        FakeResponse(204),
    ])
    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client", lambda: fake
    )
    monkeypatch.setattr(get_settings(), "public_url", "https://flowsmith.test")
    path = "gitlab-provider-registration-123456"
    _, headers, credential = _setup(
        client,
        node_type="gitlab_trigger",
        path=path,
        credential_type="gitlab",
        credential_data={"access_token": "glpat_test"},
    )
    response = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {"project": "acme/repo", "events": ["push", "merge_request"]},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["provider"] == "gitlab"
    assert data["callback_url"] == f"https://flowsmith.test/api/webhooks/{path}"
    assert data["provider_config"] == {
        "project": "acme/repo",
        "push_events": True,
        "merge_requests_events": True,
        "tag_push_events": False,
    }

    db = get_session()
    try:
        row = db.get(ProviderWebhookRegistration, data["id"])
        assert row is not None
        secret = decrypt_text(row.signing_secret)
    finally:
        db.close()
    assert secret

    created = fake.calls[0]
    assert created["method"] == "POST"
    assert created["url"] == "https://gitlab.com/api/v4/projects/acme%2Frepo/hooks"
    assert created["headers"]["PRIVATE-TOKEN"] == "glpat_test"
    assert created["json"] == {
        "url": f"https://flowsmith.test/api/webhooks/{path}",
        "token": secret,
        "push_events": True,
        "merge_requests_events": True,
        "tag_push_events": False,
    }

    payload = b'{"object_kind":"push"}'
    accepted = client.post(
        f"/api/webhooks/{path}",
        content=payload,
        headers={"X-Gitlab-Token": secret},
    )
    assert accepted.status_code == 202, accepted.text
    assert client.post(
        f"/api/webhooks/{path}",
        content=payload,
        headers={"X-Gitlab-Token": "wrong-token"},
    ).status_code == 401
    assert client.post(f"/api/webhooks/{path}", content=payload).status_code == 401

    removed = client.delete(f"/api/provider-webhooks/{data['id']}", headers=headers)
    assert removed.status_code == 200, removed.text
    deleted = fake.calls[-1]
    assert deleted["method"] == "DELETE"
    assert deleted["url"] == "https://gitlab.com/api/v4/projects/acme%2Frepo/hooks/42"
    assert deleted["headers"]["PRIVATE-TOKEN"] == "glpat_test"
    db = get_session()
    try:
        assert db.get(ProviderWebhookRegistration, data["id"]) is None
    finally:
        db.close()


def test_gitlab_registration_uses_credential_host(client, monkeypatch):
    fake = FakeClient([
        FakeResponse(201, {"id": 44}),
        FakeResponse(204),
    ])
    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client", lambda: fake
    )
    monkeypatch.setattr(get_settings(), "public_url", "https://flowsmith.test")
    path = "gitlab-self-hosted-registration-123456"
    _, headers, credential = _setup(
        client,
        node_type="gitlab_trigger",
        path=path,
        credential_type="gitlab",
        credential_data={
            "access_token": "glpat_test",
            "host": "https://gitlab.example.com",
        },
    )
    response = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {"project": "acme/repo", "events": ["push"]},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    reg_id = response.json()["data"]["id"]
    assert fake.calls[0]["url"] == "https://gitlab.example.com/api/v4/projects/acme%2Frepo/hooks"
    assert client.delete(f"/api/provider-webhooks/{reg_id}", headers=headers).status_code == 200
    assert fake.calls[-1]["url"] == "https://gitlab.example.com/api/v4/projects/acme%2Frepo/hooks/44"


def test_gitlab_registration_supports_explicit_event_flags(client, monkeypatch):
    fake = FakeClient([
        FakeResponse(201, {"id": 43}),
        FakeResponse(204),
    ])
    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client", lambda: fake
    )
    monkeypatch.setattr(get_settings(), "public_url", "https://flowsmith.test")
    path = "gitlab-provider-flags-123456789"
    _, headers, credential = _setup(
        client,
        node_type="gitlab_trigger",
        path=path,
        credential_type="gitlab",
        credential_data={"access_token": "glpat_test"},
    )
    response = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {
                "project": "acme/subgroup/repo",
                "push_events": False,
                "merge_requests_events": True,
                "tag_push_events": True,
            },
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = fake.calls[0]["json"]
    assert body["push_events"] is False
    assert body["merge_requests_events"] is True
    assert body["tag_push_events"] is True
    assert fake.calls[0]["url"] == (
        "https://gitlab.com/api/v4/projects/acme%2Fsubgroup%2Frepo/hooks"
    )
    reg_id = response.json()["data"]["id"]
    assert client.delete(f"/api/provider-webhooks/{reg_id}", headers=headers).status_code == 200


def test_gitlab_registration_rejects_invalid_project(client, monkeypatch):
    fake = FakeClient([])
    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client", lambda: fake
    )
    monkeypatch.setattr(get_settings(), "public_url", "https://flowsmith.test")
    path = "gitlab-provider-invalid-123456789"
    _, headers, credential = _setup(
        client,
        node_type="gitlab_trigger",
        path=path,
        credential_type="gitlab",
        credential_data={"access_token": "glpat_test"},
    )
    response = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {"project": "not-a-project"},
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "group/project" in response.json()["detail"]
    assert fake.calls == []


def test_stripe_registration_uses_returned_signing_secret(client, monkeypatch):
    fake = FakeClient([
        FakeResponse(200, {"id": "we_test", "secret": "whsec_provider"}),
        FakeResponse(200, {}),
    ])
    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client", lambda: fake
    )
    monkeypatch.setattr(get_settings(), "public_url", "https://flowsmith.test")
    path = "stripe-provider-registration-123456"
    _, headers, credential = _setup(
        client,
        node_type="stripe_trigger",
        path=path,
        credential_type="stripe",
        credential_data={"secret_key": "sk_test"},
    )
    response = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {"events": ["invoice.paid"]},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    reg_id = response.json()["data"]["id"]

    timestamp = str(int(time.time()))
    payload = b'{"type":"invoice.paid"}'
    signature = hmac.new(
        b"whsec_provider",
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    accepted = client.post(
        f"/api/webhooks/{path}",
        content=payload,
        headers={"stripe-signature": f"t={timestamp},v1={signature}"},
    )
    assert accepted.status_code == 202, accepted.text
    assert client.delete(f"/api/provider-webhooks/{reg_id}", headers=headers).status_code == 200


def test_shopify_registration_and_signature(client, monkeypatch):
    fake = FakeClient([
        FakeResponse(201, {"webhook": {"id": 789}}),
        FakeResponse(200, {}),
    ])
    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client", lambda: fake
    )
    monkeypatch.setattr(get_settings(), "public_url", "https://flowsmith.test")
    path = "shopify-provider-registration-123456"
    _, headers, credential = _setup(
        client,
        node_type="shopify_trigger",
        path=path,
        credential_type="shopify",
        credential_data={
            "shop_domain": "acme.myshopify.com",
            "access_token": "shpat_test",
        },
    )
    response = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
            "config": {"topic": "orders/create"},
            "signing_secret": "shopify-secret",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    reg_id = response.json()["data"]["id"]
    payload = b'{"id":1}'
    signature = hmac.new(b"shopify-secret", payload, hashlib.sha256).digest()
    accepted = client.post(
        f"/api/webhooks/{path}",
        content=payload,
        headers={"x-shopify-hmac-sha256": base64.b64encode(signature).decode()},
    )
    assert accepted.status_code == 202, accepted.text
    assert fake.calls[0]["url"] == "https://acme.myshopify.com/admin/api/2024-10/webhooks.json"
    assert client.delete(f"/api/provider-webhooks/{reg_id}", headers=headers).status_code == 200


def test_typeform_registration_and_signature(client, monkeypatch):
    fake = FakeClient([
        FakeResponse(200, {}),
        FakeResponse(204),
    ])
    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client", lambda: fake
    )
    monkeypatch.setattr(get_settings(), "public_url", "https://flowsmith.test")
    path = "typeform-provider-registration-123456"
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
            "config": {"form_id": "form_123"},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    reg_id = response.json()["data"]["id"]

    db = get_session()
    try:
        row = db.get(ProviderWebhookRegistration, reg_id)
        secret = decrypt_text(row.signing_secret)
    finally:
        db.close()

    payload = b'{"event_id":"e1"}'
    signature = base64.b64encode(
        hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    ).decode()
    accepted = client.post(
        f"/api/webhooks/{path}",
        content=payload,
        headers={"typeform-signature": f"sha256={signature}"},
    )
    assert accepted.status_code == 202, accepted.text
    assert fake.calls[0]["url"] == "https://api.typeform.com/forms/form_123/webhooks/flowsmith"
    assert client.delete(f"/api/provider-webhooks/{reg_id}", headers=headers).status_code == 200


def test_slack_registration_is_explicitly_unsupported(client):
    path = "slack-provider-registration-123456"
    _, headers, credential = _setup(
        client,
        node_type="slack_trigger",
        path=path,
        credential_type="http",
        credential_data={"url": "https://example.com"},
    )
    response = client.post(
        "/api/provider-webhooks/register",
        json={
            "workflow_id": f"wf_{path}",
            "node_id": "trigger",
            "credential_id": credential["id"],
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "dashboard" in response.json()["detail"].lower()


def test_reaper_removes_registration_for_deactivated_workflow(client, monkeypatch):
    fake = FakeClient([
        FakeResponse(201, {"id": 456}),
        FakeResponse(204),
    ])
    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client", lambda: fake
    )
    monkeypatch.setattr(get_settings(), "public_url", "https://flowsmith.test")
    path = "github-reaper-registration-123456789"
    _, headers, credential = _setup(
        client,
        node_type="github_trigger",
        path=path,
        credential_type="github",
        credential_data={"access_token": "ghp_test"},
    )
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
    assert client.patch(
        f"/api/workflows/wf_{path}/active", json={"active": False}, headers=headers
    ).status_code == 200

    import asyncio
    from app.services.provider_webhook_reaper import reap_provider_webhooks

    assert asyncio.run(reap_provider_webhooks()) == 1
    db = get_session()
    try:
        assert db.scalar(
            select(ProviderWebhookRegistration).where(
                ProviderWebhookRegistration.workflow_id == f"wf_{path}"
            )
        ) is None
    finally:
        db.close()
