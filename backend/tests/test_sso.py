"""Tests for SSO endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestSsoProviders:
    """GET /api/auth/sso/providers returns configured providers."""

    def test_no_providers_by_default(self, client):
        resp = client.get("/api/auth/sso/providers")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_returns_google_when_configured(self, client, monkeypatch):
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "sso_google_client_id", "test-google-id")
        monkeypatch.setattr(settings, "sso_google_client_secret", "test-google-secret")
        resp = client.get("/api/auth/sso/providers")
        assert resp.status_code == 200
        providers = resp.json()["data"]
        ids = [p["id"] for p in providers]
        assert "google" in ids

    def test_returns_github_when_configured(self, client, monkeypatch):
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "sso_github_client_id", "test-gh-id")
        monkeypatch.setattr(settings, "sso_github_client_secret", "test-gh-secret")
        resp = client.get("/api/auth/sso/providers")
        assert resp.status_code == 200
        providers = resp.json()["data"]
        ids = [p["id"] for p in providers]
        assert "github" in ids


class TestSsoLogin:
    """GET /api/auth/sso/{provider}/login redirects to provider."""

    def test_unconfigured_provider_404(self, client):
        resp = client.get("/api/auth/sso/google/login", follow_redirects=False)
        assert resp.status_code == 404

    def test_configured_provider_redirects(self, client, monkeypatch):
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "sso_google_client_id", "test-id")
        monkeypatch.setattr(settings, "sso_google_client_secret", "test-secret")
        resp = client.get("/api/auth/sso/google/login", follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "accounts.google.com" in location
        assert "client_id=test-id" in location
        assert "state=" in location


class TestSsoCallback:
    """GET /api/auth/sso/{provider}/callback validates state."""

    def test_invalid_state_rejected(self, client, monkeypatch):
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "sso_google_client_id", "test-id")
        monkeypatch.setattr(settings, "sso_google_client_secret", "test-secret")
        resp = client.get(
            "/api/auth/sso/google/callback",
            params={"code": "fake-code", "state": "invalid-state"},
            follow_redirects=False,
        )
        assert resp.status_code == 400


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _fake_async_client(profile, emails):
    """httpx.AsyncClient stand-in returning canned SSO responses."""

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            return _FakeResp({"access_token": "fake-access-token"})

        async def get(self, url, **kwargs):
            if "user/emails" in url:
                return _FakeResp(emails)
            return _FakeResp(profile)

    return _FakeAsyncClient


class TestSsoVerifiedEmail:
    """H2: SSO must only trust VERIFIED email addresses (account takeover)."""

    @staticmethod
    def _start_login(client, provider):
        from urllib.parse import parse_qs, urlparse

        resp = client.get(f"/api/auth/sso/{provider}/login", follow_redirects=False)
        assert resp.status_code == 302
        qs = parse_qs(urlparse(resp.headers["location"]).query)
        return qs["state"][0]

    def test_github_unverified_email_rejected(self, client, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "sso_github_client_id", "gh-id")
        monkeypatch.setattr(get_settings(), "sso_github_client_secret", "gh-secret")
        monkeypatch.setattr(
            "app.api.sso.httpx.AsyncClient",
            _fake_async_client(
                {"login": "attacker", "name": "Attacker"},
                [{"email": "victim@example.com", "primary": False, "verified": False}],
            ),
        )
        state = self._start_login(client, "github")
        resp = client.get(
            "/api/auth/sso/github/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "verified email" in resp.json()["detail"]

    def test_github_verified_email_accepted(self, client, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "sso_github_client_id", "gh-id")
        monkeypatch.setattr(get_settings(), "sso_github_client_secret", "gh-secret")
        monkeypatch.setattr(
            "app.api.sso.httpx.AsyncClient",
            _fake_async_client(
                {"login": "devuser", "name": "Dev User"},
                [
                    {"email": "other@example.com", "primary": False, "verified": False},
                    {"email": "devuser@example.com", "primary": True, "verified": True},
                ],
            ),
        )
        state = self._start_login(client, "github")
        resp = client.get(
            "/api/auth/sso/github/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "sso_token=" in resp.headers["location"]

    def test_oidc_unverified_email_rejected(self, client, monkeypatch):
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "sso_oidc_client_id", "oidc-id")
        monkeypatch.setattr(settings, "sso_oidc_client_secret", "oidc-secret")
        monkeypatch.setattr(settings, "sso_oidc_issuer", "https://issuer.example")
        monkeypatch.setattr(
            "app.api.sso.httpx.AsyncClient",
            _fake_async_client(
                {"email": "victim@example.com", "email_verified": False, "name": "V"},
                [],
            ),
        )
        state = self._start_login(client, "oidc")
        resp = client.get(
            "/api/auth/sso/oidc/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert "verified email" in resp.json()["detail"]
