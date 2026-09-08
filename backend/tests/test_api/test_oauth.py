"""Connect Salesforce OAuth tests (Phase 21):

- connect endpoint: auth required, server config required, authorize URL + state
- callback endpoint: state validation (missing/invalid/used/expired), code
  exchange, encrypted credential creation, reconnect replacement, failure path
- provider: server-side client id/secret injection for OAuth connections
- credential model: OAuth-mode validation

The external Salesforce calls (token exchange + identity lookup) are scripted
at the SafeHTTPClient seam, the same pattern used by test_salesforce_credentials.py.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config import Settings
from app.connectors import get_registry, register_builtin_connectors
from app.db import get_session
from app.models import Credential, OAuthState, User
from app.providers.salesforce import SalesforceProviderClient
from app.security.crypto import decrypt_text
from tests.test_api.conftest import auth_headers, register


def _settings(**overrides) -> Settings:
    defaults = {
        "salesforce_client_id": "SRV_CID_123",
        "salesforce_client_secret": "SRV_SECRET_456",
        "salesforce_redirect_uri": "http://localhost:8000/api/auth/salesforce/callback",
        "salesforce_login_url": "https://login.salesforce.com",
        "salesforce_api_version": "v63.0",
        "salesforce_scopes": "refresh_token full api",
        "oauth_state_ttl_seconds": 600,
    }
    defaults.update(overrides)
    return Settings(**defaults)


class FakeHTTPClient:
    """Scripted SafeHTTPClient replacement: records calls, returns responses in order."""

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
    monkeypatch.setattr("app.providers.salesforce.get_settings", lambda: settings)
    yield settings


@pytest.fixture(autouse=True)
def _connectors_registered():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    yield


@pytest.fixture
def client():
    """TestClient without redirect-following (callback returns 302s)."""
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    return TestClient(fastapi_app, follow_redirects=False)


def _setup(client):
    return auth_headers(register(client)["token"])


def _connect(client, headers, login_url=None) -> dict:
    body = {"login_url": login_url} if login_url else {}
    resp = client.post("/api/auth/salesforce/connect", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _error_of(location: str) -> str:
    return parse_qs(urlparse(location).query).get("error", [""])[0]


def _count_sf_credentials(client, headers) -> int:
    creds = client.get("/api/credentials", headers=headers).json()["data"]
    return len([c for c in creds if c["type"] == "salesforce"])
    creds = client.get("/api/credentials", headers=headers).json()["data"]
    return len([c for c in creds if c["type"] == "salesforce"])


TOKEN_PAYLOAD = {
    "access_token": "access123",
    "refresh_token": "refresh_oauth_secret_999",
    "instance_url": "https://orgfarm-a3163db0ee-dev-ed.develop.my.salesforce.com",
    "id": "https://login.salesforce.com/id/00Dfake/005fake",
    "token_type": "Bearer",
    "scope": "refresh_token full api",
}


# ----------------------------------------------------------------------
# Connect endpoint
# ----------------------------------------------------------------------


def test_connect_requires_auth(client):
    resp = client.post("/api/auth/salesforce/connect", json={})
    assert resp.status_code in (401, 403)
    assert "Missing bearer token" in resp.text or "Invalid" in resp.text


def test_connect_requires_server_config(client, monkeypatch):
    from app.api import oauth as oauth_mod

    empty = Settings(
        salesforce_client_id="",
        salesforce_client_secret="",
        salesforce_redirect_uri="",
    )
    monkeypatch.setattr(oauth_mod, "get_settings", lambda: empty)
    headers = _setup(client)
    resp = client.post("/api/auth/salesforce/connect", json={}, headers=headers)
    assert resp.status_code == 422
    assert "not configured" in resp.json()["detail"]


def test_connect_returns_authorize_url_and_persists_state(client, _configure_oauth):
    headers = _setup(client)
    data = _connect(client, headers)

    assert data["authorize_url"].startswith("https://login.salesforce.com/services/oauth2/authorize?")
    assert "response_type=code" in data["authorize_url"]
    assert "client_id=SRV_CID_123" in data["authorize_url"]
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fauth%2Fsalesforce%2Fcallback" in data["authorize_url"]
    params = parse_qs(urlparse(data["authorize_url"]).query)
    assert params["state"][0] == data["state"]
    assert params["code_challenge_method"][0] == "S256"
    challenge = params["code_challenge"][0]

    db = get_session()
    try:
        row = db.get(OAuthState, data["state"])
        assert row is not None
        user = db.get(User, row.user_id)
        assert user is not None
        assert row.user_id == user.id
        assert row.login_url == "https://login.salesforce.com"
        assert row.used is False
        assert row.code_verifier
        assert row.code_verifier not in data["authorize_url"]
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(row.code_verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert challenge == expected
    finally:
        db.close()


def test_connect_uses_custom_login_url(client, _configure_oauth):
    headers = _setup(client)
    data = _connect(client, headers, login_url="https://orgfarm-a3163db0ee-dev-ed.develop.my.salesforce.com")
    assert data["authorize_url"].startswith(
        "https://orgfarm-a3163db0ee-dev-ed.develop.my.salesforce.com/services/oauth2/authorize?"
    )


# ----------------------------------------------------------------------
# Callback endpoint
# ----------------------------------------------------------------------


def test_callback_missing_code_or_state_redirects_failed(client):
    resp = client.get("/api/auth/salesforce/callback")
    assert resp.status_code == 302
    assert "ok=0" in resp.headers["location"]


def test_callback_invalid_state_redirects_failed(client, _configure_oauth):
    resp = client.get("/api/auth/salesforce/callback?code=c1&state=forged")
    assert resp.status_code == 302
    assert "ok=0" in resp.headers["location"]
    assert _error_of(resp.headers["location"]) == "invalid state"


def test_callback_rejects_used_state(client, _configure_oauth):
    headers = _setup(client)
    state = _connect(client, headers)["state"]
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_PAYLOAD),
        _json_response(200, {"username": "user@example.com"}),
    ])
    try:
        first = client.get(f"/api/auth/salesforce/callback?code=good1&state={state}")
        assert first.status_code == 302
        assert "ok=1" in first.headers["location"]
        second = client.get(f"/api/auth/salesforce/callback?code=replay&state={state}")
        assert second.status_code == 302
        assert _error_of(second.headers["location"]) == "state already used"
    finally:
        patcher.stop()


def test_callback_success_creates_encrypted_credential(client, _configure_oauth):
    headers = _setup(client)
    state = _connect(client, headers)["state"]
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_PAYLOAD),
        _json_response(200, {"username": "user@example.com"}),
    ])
    try:
        resp = client.get(f"/api/auth/salesforce/callback?code=good1&state={state}")
    finally:
        patcher.stop()

    assert resp.status_code == 302
    assert "ok=1" in resp.headers["location"]

    # The token exchange hit the org's authorization server with the
    # server-side client id/secret.
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://login.salesforce.com/services/oauth2/token"
    assert "grant_type=authorization_code" in kwargs["data"]
    assert "code=good1" in kwargs["data"]
    assert "client_id=SRV_CID_123" in kwargs["data"]
    assert "client_secret=SRV_SECRET_456" in kwargs["data"]
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fauth%2Fsalesforce%2Fcallback" in kwargs["data"]

    # The token exchange asks for an uncompressed body (Salesforce/F5
    # gzip quirk) so the single-use code never needs a replay.
    assert kwargs["headers"]["Accept-Encoding"] == "identity"
    # The body is pre-encoded: the form content type MUST be explicit,
    # otherwise Salesforce answers unsupported_grant_type (Phase 36 fix).
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

    # PKCE: the token exchange sends the verifier bound to the state row.
    db = get_session()
    try:
        row = db.get(OAuthState, state)
        assert row is not None
        assert f"code_verifier={row.code_verifier}" in kwargs["data"]
    finally:
        db.close()

# Identity lookup used the access token, which is never persisted.
    _method, _get_url, get_kwargs = fake.calls[1]
    assert get_kwargs["headers"]["Authorization"] == "Bearer access123"
    assert get_kwargs["headers"]["Accept-Encoding"] == "identity"

    creds = client.get("/api/credentials", headers=headers).json()["data"]
    assert len(creds) == 1
    assert creds[0]["type"] == "salesforce"
    assert creds[0]["name"] == "Salesforce (user@example.com)"

    db = get_session()
    try:
        rec = db.get(Credential, creds[0]["id"])
        assert rec is not None
        assert b"refresh_oauth_secret_999" not in rec.data  # encrypted at rest
        plain = json.loads(decrypt_text(rec.data))
        assert plain["refresh_token"] == "refresh_oauth_secret_999"
        assert plain["oauth"] is True
        assert plain["instance_url"] == TOKEN_PAYLOAD["instance_url"]
        assert plain["login_url"] == "https://login.salesforce.com"
        assert plain["username"] == "user@example.com"
        assert plain["client_id"] == ""
        assert plain["client_secret"] == ""
    finally:
        db.close()


def test_callback_reconnect_replaces_previous_connection(client, _configure_oauth):
    headers = _setup(client)
    state1 = _connect(client, headers)["state"]
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_PAYLOAD),
        _json_response(200, {"username": "user@example.com"}),
    ])
    try:
        client.get(f"/api/auth/salesforce/callback?code=c1&state={state1}")
    finally:
        patcher.stop()
    assert _count_sf_credentials(client, headers) == 1

    state2 = _connect(client, headers)["state"]
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_PAYLOAD),
        _json_response(200, {"username": "user@example.com"}),
    ])
    try:
        client.get(f"/api/auth/salesforce/callback?code=c2&state={state2}")
    finally:
        patcher.stop()

    creds = client.get("/api/credentials", headers=headers).json()["data"]
    assert len(creds) == 1  # previous OAuth connection replaced
    assert creds[0]["name"] == "Salesforce (user@example.com)"


def test_callback_failure_creates_no_credential(client, _configure_oauth):
    headers = _setup(client)
    state = _connect(client, headers)["state"]
    patcher, _fake = _patch_client([
        _json_response(400, {"error": "invalid_grant", "error_description": "expired authorization code"}),
    ])
    try:
        resp = client.get(f"/api/auth/salesforce/callback?code=bad&state={state}")
    finally:
        patcher.stop()

    assert resp.status_code == 302
    assert "ok=0" in resp.headers["location"]
    assert _error_of(resp.headers["location"]) == "expired authorization code"
    assert _count_sf_credentials(client, headers) == 0


# ----------------------------------------------------------------------
# Multi-user isolation
# ----------------------------------------------------------------------


def test_oauth_connection_scoped_to_owning_user(client, _configure_oauth):
    headers_a = _setup(client)
    state = _connect(client, headers_a)["state"]
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_PAYLOAD),
        _json_response(200, {"username": "a@example.com"}),
    ])
    try:
        client.get(f"/api/auth/salesforce/callback?code=c1&state={state}")
    finally:
        patcher.stop()

    # User B cannot see or use A's connection.
    headers_b = auth_headers(register(client, email="b@b.com")["token"])
    assert _count_sf_credentials(client, headers_b) == 0

    # A forged callback with B's identity cannot reuse A's state (state is
    # bound to A in the oauth_states table).
    resp = client.get(f"/api/auth/salesforce/callback?code=c2&state={state}", headers=headers_b)
    assert resp.status_code == 302
    assert _error_of(resp.headers["location"]) == "state already used"
    assert _count_sf_credentials(client, headers_b) == 0


# ----------------------------------------------------------------------
# Provider: server-side config injection for OAuth connections
# ----------------------------------------------------------------------


async def test_provider_injects_server_config_for_oauth_credentials(_configure_oauth):
    patcher, fake = _patch_provider_client([
        _json_response(200, TOKEN_PAYLOAD),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        provider = SalesforceProviderClient()
        creds = {
            "instance_url": "https://orgfarm-a3163db0ee-dev-ed.develop.my.salesforce.com",
            "login_url": "https://login.salesforce.com",
            "refresh_token": "refresh_oauth_secret_999",
            "username": "user@example.com",
            "oauth": True,
            "api_version": "v63.0",
            "client_id": "",
            "client_secret": "",
        }
        await provider.query(creds, "SELECT Id FROM Account")
    finally:
        patcher.stop()

    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://login.salesforce.com/services/oauth2/token"
    assert "client_id=SRV_CID_123" in kwargs["data"]
    assert "client_secret=SRV_SECRET_456" in kwargs["data"]
    assert "refresh_token=refresh_oauth_secret_999" in kwargs["data"]


def _patch_provider_client(responses: list[httpx.Response]):
    fake = FakeHTTPClient(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.providers.salesforce.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher, fake


# ----------------------------------------------------------------------
# Credential model: OAuth mode
# ----------------------------------------------------------------------


def test_oauth_credential_requires_refresh_token(client):
    headers = _setup(client)
    data = {
        "instance_url": "https://orgfarm-a3163db0ee-dev-ed.develop.my.salesforce.com",
        "oauth": True,
        "client_id": "",
        "client_secret": "",
    }
    resp = client.post("/api/credentials", json={"name": "SF OAuth", "type": "salesforce", "data": data}, headers=headers)
    assert resp.status_code == 422, resp.text


def test_oauth_credential_allows_empty_client_id_secret(client):
    headers = _setup(client)
    data = {
        "instance_url": "https://orgfarm-a3163db0ee-dev-ed.develop.my.salesforce.com",
        "refresh_token": "refresh_oauth_secret_999",
        "oauth": True,
        "username": "user@example.com",
        "client_id": "",
        "client_secret": "",
    }
    resp = client.post("/api/credentials", json={"name": "SF OAuth", "type": "salesforce", "data": data}, headers=headers)
    assert resp.status_code == 201, resp.text

    db = get_session()
    try:
        meta = resp.json()["data"]
        assert meta is not None
        rec = db.get(Credential, meta["id"])
        assert rec is not None
        assert b"refresh_oauth_secret_999" not in rec.data
        plain = json.loads(decrypt_text(rec.data))
        assert plain["oauth"] is True
    finally:
        db.close()

