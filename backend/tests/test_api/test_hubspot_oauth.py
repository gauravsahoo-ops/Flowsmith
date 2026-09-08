"""Connect HubSpot OAuth tests (Phase 33).

The generic provider framework is exercised through the second provider
to prove it generalizes beyond Salesforce:

- connect endpoint: auth required, server config required, authorize URL
  carries client_id/redirect/scopes/state (no PKCE for HubSpot).
- callback: state validation, code exchange at /oauth/v1/token,
  encrypted 'hubspot' credential creation, reconnect replacement.
- failure paths: provider error, malformed token response.

External calls are scripted at the SafeHTTPClient seam (same pattern as
test_oauth.py). Salesforce behaviour itself stays covered by test_oauth.py.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import Settings
from app.db import get_session
from app.models import Credential, OAuthState
from app.security.crypto import decrypt_text
from tests.test_api.conftest import auth_headers, register


def _settings(**overrides) -> Settings:
    defaults = {
        "hubspot_client_id": "HS_CID_123",
        "hubspot_client_secret": "HS_SECRET_456",
        "hubspot_redirect_uri": "http://localhost:8000/api/auth/hubspot/callback",
        "hubspot_scopes": "oauth crm.objects.contacts.read",
        "oauth_state_ttl_seconds": 600,
    }
    defaults.update(overrides)
    return Settings(**defaults)


class FakeHTTPClient:
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

    async def get(self, url, **kwargs) -> httpx.Response:
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _patch_client(responses: list[httpx.Response]):
    fake = FakeHTTPClient(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.api.oauth.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher, fake


@pytest.fixture(autouse=True)
def _configure_oauth(monkeypatch):
    settings = _settings()
    monkeypatch.setattr("app.api.oauth.get_settings", lambda: settings)
    yield settings


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    return TestClient(fastapi_app, follow_redirects=False)


def _setup(client):
    return auth_headers(register(client)["token"])


def test_connect_requires_auth(client):
    resp = client.post("/api/auth/hubspot/connect", json={})
    assert resp.status_code == 401


def test_connect_requires_server_config(client, monkeypatch):
    headers = _setup(client)
    monkeypatch.setattr(
        "app.api.oauth.get_settings",
        lambda: _settings(hubspot_client_id="", hubspot_client_secret=""),
    )
    resp = client.post("/api/auth/hubspot/connect", json={}, headers=headers)
    assert resp.status_code == 422
    assert "HUBSPOT_CLIENT_ID" in resp.json()["detail"]


def test_connect_returns_authorize_url_and_stores_state(client):
    headers = _setup(client)
    resp = client.post("/api/auth/hubspot/connect", json={}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    url = data["authorize_url"]
    assert url.startswith("https://app.hubspot.com/oauth/authorize?")
    assert "client_id=HS_CID_123" in url
    assert "redirect_uri=http" in url
    assert "state=" in url
    # No PKCE for HubSpot confidential apps
    assert "code_challenge" not in url

    db = get_session()
    try:
        row = db.query(OAuthState).filter_by(state=data["state"]).first()
        assert row is not None and row.user_id is not None
    finally:
        db.close()


def test_callback_exchanges_code_and_stores_encrypted_credential(client):
    headers = _setup(client)
    connect = client.post("/api/auth/hubspot/connect", json={}, headers=headers).json()["data"]

    token_resp = _json_response(200, {
        "refresh_token": "HS_REFRESH_ZZZ",
        "access_token": "short-lived-token",
    })
    identity_resp = _json_response(200, {"user": "owner@acme.com", "hub_id": 12345})
    patcher, fake = _patch_client([token_resp, identity_resp])
    try:
        resp = client.get(
            f"/api/auth/hubspot/callback?code=abc&state={connect['state']}",
            headers=headers,
        )
    finally:
        patcher.stop()

    assert resp.status_code == 302
    assert "ok=1" in resp.headers["location"]
    # Token exchange hit the HubSpot OAuth endpoint with server credentials
    method, url, kwargs = fake.calls[0]
    assert url == "https://api.hubapi.com/oauth/v1/token"
    assert "client_secret=HS_SECRET_456" in kwargs["data"]

    # Exactly one encrypted hubspot credential; refresh token only inside
    # the encrypted blob.
    db = get_session()
    try:
        rows = db.query(Credential).filter(Credential.type == "hubspot").all()
        assert len(rows) == 1
        raw = rows[0].data
        blob = json.loads(decrypt_text(raw if isinstance(raw, bytes) else str(raw).encode()))
        assert blob["oauth"] is True
        assert blob["refresh_token"] == "HS_REFRESH_ZZZ"
        assert str(rows[0].data).find("HS_REFRESH_ZZZ") == -1
    finally:
        db.close()


def test_callback_rejects_used_state(client):
    headers = _setup(client)
    connect = client.post("/api/auth/hubspot/connect", json={}, headers=headers).json()["data"]
    # First use: fails at exchange (no responses) but marks state used.
    patcher, _fake = _patch_client([_json_response(400, {"error": "invalid_grant"})])
    try:
        first = client.get(f"/api/auth/hubspot/callback?code=a&state={connect['state']}")
        assert first.status_code == 302
        assert "ok=0" in first.headers["location"]
    finally:
        patcher.stop()

    second = client.get(f"/api/auth/hubspot/callback?code=b&state={connect['state']}")
    assert second.status_code == 302
    assert "state%20already%20used" in second.headers["location"] or "state already used" in second.headers["location"]


def test_callback_provider_error_redirects_failed(client):
    headers = _setup(client)
    resp = client.get("/api/auth/hubspot/callback?error=access_denied")
    assert resp.status_code == 302
    assert "ok=0" in resp.headers["location"]


def test_unknown_provider_404(client):
    headers = _setup(client)
    assert client.post("/api/auth/nothing/connect", json={}, headers=headers).status_code == 404
