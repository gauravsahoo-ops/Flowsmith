"""Unit and integration tests for Credential Auto-Reconnect and Proactive Renewal Engine."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.credentials.auto_reconnect import (
    auto_refresh_all_expiring_credentials,
    can_auto_reconnect,
    is_credential_expiring,
)
from app.db import get_session
from app.models import Credential
from app.security.crypto import decrypt_text, encrypt_text
from tests.test_api.conftest import auth_headers, register


def test_is_credential_expiring():
    now = time.time()
    # Expiring in 10 minutes (within default 30 min window)
    assert is_credential_expiring({"expires_at": now + 600}) is True
    # Expired 5 minutes ago
    assert is_credential_expiring({"expires_at": now - 300}) is True
    # Expiring in 2 hours (outside default 30 min window)
    assert is_credential_expiring({"expires_at": now + 7200}) is False
    # No expires_at field
    assert is_credential_expiring({}) is False


def test_can_auto_reconnect():
    # Salesforce with password auth
    assert can_auto_reconnect("salesforce", {"username": "user@org.com", "password": "pwd"}) is True
    # Salesforce with refresh token
    assert can_auto_reconnect("salesforce", {"refresh_token": "sf_refresh_123"}) is True
    # Salesforce without auth credentials
    assert can_auto_reconnect("salesforce", {"instance_url": "https://foo.salesforce.com"}) is False

    # OAuth provider with refresh token
    assert can_auto_reconnect("google_calendar", {"refresh_token": "rt_123"}) is True
    assert can_auto_reconnect("hubspot", {"refresh_token": "hs_rt_123"}) is True

    # Static / manual credentials without refresh token
    assert can_auto_reconnect("google_calendar", {"access_token": "tok"}) is False
    assert can_auto_reconnect("smtp", {"host": "smtp.example.com"}) is False


@pytest.mark.asyncio
async def test_auto_refresh_all_expiring_credentials(client):
    user_info = register(client, email="autorefresh_worker@example.com")
    db = get_session()
    try:
        now = time.time()
        # 1. Credential expiring soon
        c1 = Credential(
            id="cred-expiring-1",
            user_id=user_info["user"]["id"],
            name="Expiring Google",
            type="google_calendar",
            data=encrypt_text(json.dumps({
                "access_token": "old_token",
                "refresh_token": "valid_refresh",
                "expires_at": now + 300,  # in 5 minutes
            })),
        )
        # 2. Credential far in the future
        c2 = Credential(
            id="cred-valid-2",
            user_id=user_info["user"]["id"],
            name="Valid Google",
            type="google_calendar",
            data=encrypt_text(json.dumps({
                "access_token": "current_token",
                "refresh_token": "valid_refresh",
                "expires_at": now + 86400,
            })),
        )
        db.add_all([c1, c2])
        db.commit()

        # Mock OAuthManager.refresh
        mock_refreshed = {
            "access_token": "brand_new_token",
            "refresh_token": "valid_refresh",
            "expires_at": now + 3600,
        }
        with patch("app.credentials.oauth_manager.OAuthManager.refresh", new_callable=AsyncMock) as mock_refresh:
            mock_refresh.return_value = mock_refreshed
            stats = await auto_refresh_all_expiring_credentials(db, window_minutes=30)
            assert stats["refreshed"] >= 1

            # Verify DB was updated with new token
            db.refresh(c1)
            updated_data = json.loads(decrypt_text(c1.data))
            assert updated_data["access_token"] == "brand_new_token"
    finally:
        db.close()


def test_reconnect_credential_api_endpoint(client):
    user_info = register(client, email="reconnect_api@example.com")
    headers = auth_headers(user_info["token"])
    db = get_session()
    try:
        # Create an OAuth credential
        c = Credential(
            id="cred-to-reconnect",
            user_id=user_info["user"]["id"],
            name="My Google Calendar",
            type="google_calendar",
            data=encrypt_text(json.dumps({
                "access_token": "expired_token",
                "refresh_token": "mock_refresh_token",
                "expires_at": time.time() - 100,
            })),
        )
        db.add(c)
        db.commit()

        # Mock OAuth refresh
        with patch("app.credentials.oauth_manager.OAuthManager.refresh", new_callable=AsyncMock) as mock_refresh:
            mock_refresh.return_value = {
                "access_token": "refreshed_access_token",
                "refresh_token": "mock_refresh_token",
                "expires_at": time.time() + 3600,
            }

            resp = client.post("/api/credentials/cred-to-reconnect/reconnect", headers=headers)
            assert resp.status_code == 200, resp.text
            payload = resp.json()["data"]
            assert payload["ok"] is True
            assert payload["refreshed"] is True

            # Verify non-existent returns 404
            not_found = client.post("/api/credentials/non-existent-id/reconnect", headers=headers)
            assert not_found.status_code == 404
    finally:
        db.close()


def test_reconnect_credential_static_fails_cleanly(client):
    user_info = register(client, email="reconnect_static@example.com")
    headers = auth_headers(user_info["token"])
    db = get_session()
    try:
        # Credential that cannot be auto-reconnected
        c = Credential(
            id="cred-static-auth",
            user_id=user_info["user"]["id"],
            name="Static SMTP",
            type="smtp",
            data=encrypt_text(json.dumps({
                "host": "smtp.example.com",
                "port": 587,
            })),
        )
        db.add(c)
        db.commit()

        resp = client.post("/api/credentials/cred-static-auth/reconnect", headers=headers)
        assert resp.status_code == 200
        payload = resp.json()["data"]
        assert payload["ok"] is False
        assert payload["interactive_required"] is True
    finally:
        db.close()


def test_test_credential_auto_reconnects_when_expired(client):
    user_info = register(client, email="test_autoreconnect@example.com")
    headers = auth_headers(user_info["token"])
    db = get_session()
    try:
        c = Credential(
            id="cred-expired-for-test",
            user_id=user_info["user"]["id"],
            name="Expired Salesforce",
            type="salesforce",
            data=encrypt_text(json.dumps({
                "username": "user@org.com",
                "password": "pwd",
                "access_token": "expired_sf_token",
                "expires_at": time.time() - 3600,
            })),
        )
        db.add(c)
        db.commit()

        with patch("app.providers.salesforce.SalesforceProviderClient.authenticate", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = "new_live_sf_token"
            with patch("app.credentials.providers.salesforce.SalesforceAuthProvider.testConnection") as mock_conn:
                mock_conn.return_value = {"ok": True, "message": "Salesforce connection successful."}
                resp = client.post("/api/credentials/cred-expired-for-test/test", headers=headers)
                assert resp.status_code == 200, resp.text
                data = resp.json()["data"]
                assert data["ok"] is True
    finally:
        db.close()
