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
