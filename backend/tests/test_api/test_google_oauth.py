"""Google Calendar OAuth flow tests (Phase 37).

Third provider on the generic framework: authorize URL carries
access_type=offline & prompt=consent (refresh token guaranteed), no PKCE;
token exchange posts to oauth2.googleapis.com/token; identity label is
decoded locally from id_token; encrypted google_calendar credential is
stored with reconnect replacement.
"""

from __future__ import annotations

import base64
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
        "google_client_id": "G_CID",
        "google_client_secret": "G_SECRET",
        "google_redirect_uri": "http://localhost:8000/api/auth/google_calendar/callback",
        "google_scopes": "openid email https://www.googleapis.com/auth/calendar.events",
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


def _json(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _patch_client(responses):
    fake = FakeHTTPClient(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.api.oauth.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher, fake


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    settings = _settings()
    monkeypatch.setattr("app.api.oauth.get_settings", lambda: settings)
    yield settings


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    return TestClient(fastapi_app, follow_redirects=False)


def _id_token(email: str) -> str:
    def b64(d: bytes) -> str:
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode()

    return f"{b64(json.dumps({'alg': 'none'}).encode())}.{b64(json.dumps({'email': email}).encode())}."


def test_connect_authorize_url_requests_offline_access(client):
    headers = auth_headers(register(client)["token"])
    resp = client.post("/api/auth/google_calendar/connect", json={}, headers=headers)
    assert resp.status_code == 200
    url = resp.json()["data"]["authorize_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=G_CID" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=" in url
    assert "code_challenge" not in url


def test_callback_exchanges_and_stores_encrypted_credential(client):
    headers = auth_headers(register(client)["token"])
    state = client.post("/api/auth/google_calendar/connect", json={}, headers=headers).json()["data"]["state"]

    token = _json(200, {"refresh_token": "G_REFRESH_XYZ", "access_token": "at", "id_token": _id_token("me@gmail.com")})
    patcher, fake = _patch_client([token])
    try:
        resp = client.get(f"/api/auth/google_calendar/callback?code=c&state={state}", headers=headers)
    finally:
        patcher.stop()

    assert resp.status_code == 302
    assert "ok=1" in resp.headers["location"]
    method, url, kwargs = fake.calls[0]
    assert url == "https://oauth2.googleapis.com/token"
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

    db = get_session()
    try:
        rows = db.query(Credential).filter(Credential.type == "google_calendar").all()
        assert len(rows) == 1
        raw = rows[0].data
        blob = json.loads(decrypt_text(raw if isinstance(raw, bytes) else str(raw).encode()))
        assert blob["refresh_token"] == "G_REFRESH_XYZ"
        assert blob["user"] == "me@gmail.com"
        assert blob["oauth"] is True
    finally:
        db.close()


def test_callback_replaces_previous_oauth_connection(client):
    headers = auth_headers(register(client)["token"])
    for code in ("first", "second"):
        state = client.post("/api/auth/google_calendar/connect", json={}, headers=headers).json()["data"]["state"]
        patcher, _f = _patch_client([
            _json(200, {"refresh_token": f"G_REFRESH_{code}", "access_token": "at", "id_token": _id_token("me@gmail.com")}),
        ])
        try:
            resp = client.get(f"/api/auth/google_calendar/callback?code={code}&state={state}", headers=headers)
            assert resp.status_code == 302
        finally:
            patcher.stop()

    db = get_session()
    try:
        rows = db.query(Credential).filter(Credential.type == "google_calendar").all()
        assert len(rows) == 1
    finally:
        db.close()


def test_unknown_provider_still_404(client):
    headers = auth_headers(register(client)["token"])
    assert client.post("/api/auth/nope/connect", json={}, headers=headers).status_code == 404
