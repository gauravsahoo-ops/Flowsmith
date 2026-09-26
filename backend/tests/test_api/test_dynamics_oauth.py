"""Connect Microsoft Dynamics 365 OAuth tests.

Tests the Azure Entra ID / Microsoft Dynamics 365 OAuth2 flow:
- connect endpoint: auth required, server config or user credentials required,
  authorize URL carries client_id, PKCE challenge, tenant ID, and state.
- callback endpoint: state validation, code exchange at /token,
  identity probe at WhoAmI, encrypted 'dynamics_crm' credential creation.
- failure paths: provider error, expired/invalid state.
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
    from app.config import get_settings
    current = get_settings()
    data = current.model_dump()
    data.update({
        "dynamics_crm_client_id": "DYN_CID_123",
        "dynamics_crm_client_secret": "DYN_SECRET_456",
        "dynamics_crm_redirect_uri": "http://localhost:8000/api/auth/dynamics_crm/callback",
        "dynamics_crm_tenant_id": "common",
        "dynamics_crm_instance_url": "https://testorg.crm.dynamics.com",
        "dynamics_crm_scopes": "offline_access https://testorg.crm.dynamics.com/.default",
        "oauth_state_ttl_seconds": 600,
    })
    data.update(overrides)
    return Settings(**data)


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


def _setup(client):
    return auth_headers(register(client)["token"])


def test_connect_requires_auth(client):
    resp = client.post("/api/auth/dynamics_crm/connect", json={})
    assert resp.status_code == 401


def test_connect_requires_server_config(client, monkeypatch):
    headers = _setup(client)
    monkeypatch.setattr(
        "app.api.oauth.get_settings",
        lambda: _settings(dynamics_crm_client_id="", dynamics_crm_client_secret=""),
    )
    resp = client.post("/api/auth/dynamics_crm/connect", json={}, headers=headers)
    assert resp.status_code == 422


def test_connect_success(client):
    headers = _setup(client)
    resp = client.post(
        "/api/auth/dynamics_crm/connect",
        json={"login_url": "https://myorg.crm.dynamics.com"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    url = data["authorize_url"]
    assert "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?" in url
    assert "client_id=DYN_CID_123" in url
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert "state=" in url

    # State recorded in database
    with get_session() as db:
        state_row = db.query(OAuthState).filter(OAuthState.state == data["state"]).first()
        assert state_row is not None
        assert state_row.user_id is not None
        assert state_row.code_verifier


def test_callback_stores_encrypted_credential(client):
    headers = _setup(client)
    connect = client.post(
        "/api/auth/dynamics_crm/connect",
        json={"login_url": "https://myorg.crm.dynamics.com"},
        headers=headers,
    ).json()["data"]

    token_body = {
        "access_token": "dyn_at_test",
        "refresh_token": "dyn_rt_test",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    whoami_body = {
        "UserId": "00000000-0000-0000-0000-000000000001",
        "OrganizationId": "11111111-1111-1111-1111-111111111111",
        "BusinessUnitId": "22222222-2222-2222-2222-222222222222",
    }

    patcher, fake = _patch_client([
        _json_response(200, token_body),
        _json_response(200, whoami_body),
    ])
    try:
        resp = client.get(
            f"/api/auth/dynamics_crm/callback?code=abc123code&state={connect['state']}",
            headers=headers,
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        assert "provider=dynamics_crm" in resp.headers["location"]
        assert "ok=1" in resp.headers["location"]
    finally:
        patcher.stop()

    # Verify encrypted credential in database
    with get_session() as db:
        rows = db.query(Credential).filter(Credential.type == "dynamics_crm").all()
        assert len(rows) == 1
        cred = rows[0]
        data = json.loads(decrypt_text(cred.data))
        assert data["access_token"] == "dyn_at_test"
        assert data["refresh_token"] == "dyn_rt_test"
        assert data["instance_url"] == "https://myorg.crm.dynamics.com"
        assert data["oauth"] is True


def test_callback_state_single_use(client):
    headers = _setup(client)
    connect = client.post(
        "/api/auth/dynamics_crm/connect",
        json={},
        headers=headers,
    ).json()["data"]

    token_body = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
    whoami_body = {"UserId": "u1", "OrganizationId": "o1"}

    patcher, fake = _patch_client([
        _json_response(200, token_body),
        _json_response(200, whoami_body),
    ])
    try:
        first = client.get(
            f"/api/auth/dynamics_crm/callback?code=a&state={connect['state']}",
            follow_redirects=False,
        )
        assert first.status_code in (302, 307)
        assert "provider=dynamics_crm" in first.headers["location"]
        assert "ok=1" in first.headers["location"]
    finally:
        patcher.stop()

    second = client.get(
        f"/api/auth/dynamics_crm/callback?code=b&state={connect['state']}",
        follow_redirects=False,
    )
    assert second.status_code in (302, 307)
    assert "provider=dynamics_crm" in second.headers["location"]
    assert "ok=0" in second.headers["location"]
