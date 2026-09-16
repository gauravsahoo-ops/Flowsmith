"""Unit and integration tests for Credential Auto-Reconnect and Proactive Renewal Engine."""

from __future__ import annotations

import json
import time
import uuid
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
    suffix = uuid.uuid4().hex[:8]
    c1_id = f"cred-expiring-{suffix}"
    c2_id = f"cred-valid-{suffix}"
    try:
        now = time.time()
        # 1. Credential expiring soon
        c1 = Credential(
            id=c1_id,
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
            id=c2_id,
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

            # Breakdown invariant: skipped is always the sum of its parts.
            assert stats["skipped"] == (
                stats["skipped_locked"] + stats["skipped_deleted"]
                + stats["skipped_decrypt"] + stats["skipped_not_eligible"]
                + stats["skipped_unverified"]
            )

            # Verify DB was updated with new token
            db.refresh(c1)
            updated_data = json.loads(decrypt_text(c1.data))
            assert updated_data["access_token"] == "brand_new_token"

            # Far-future credential must be untouched
            db.refresh(c2)
            untouched = json.loads(decrypt_text(c2.data))
            assert untouched["access_token"] == "current_token"

            # Sweep wrote exactly one summary audit page (single owner).
            from app.models import AuditEvent

            rows = db.query(AuditEvent).filter(
                AuditEvent.action == "credential.auto_refresh_sweep"
            ).all()
            assert len(rows) == 1
            detail = rows[0].detail or {}
            assert detail["page"] == 1 and detail["pages"] == 1
            assert detail["user_count"] == 1
            assert user_info["user"]["id"] in detail["user_ids"]

            # Helper reassembles the sweep without hand-grouping pages.
            from app.audit import collect_sweep_audit

            assembled = collect_sweep_audit(db, detail["sweep_id"])
            assert assembled["complete"] is True
            assert assembled["user_ids"] == [user_info["user"]["id"]]
            assert assembled["stats"]["refreshed"] >= 1
    finally:
        db.close()


def test_reconnect_credential_api_endpoint(client):
    user_info = register(client, email="reconnect_api@example.com")
    headers = auth_headers(user_info["token"])
    db = get_session()
    cred_id = f"cred-to-reconnect-{uuid.uuid4().hex[:8]}"
    try:
        # Create an OAuth credential
        c = Credential(
            id=cred_id,
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

            resp = client.post(f"/api/credentials/{cred_id}/reconnect", headers=headers)
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
    cred_id = f"cred-static-auth-{uuid.uuid4().hex[:8]}"
    try:
        # Credential that cannot be auto-reconnected
        c = Credential(
            id=cred_id,
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

        resp = client.post(f"/api/credentials/{cred_id}/reconnect", headers=headers)
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
    cred_id = f"cred-expired-for-test-{uuid.uuid4().hex[:8]}"
    try:
        c = Credential(
            id=cred_id,
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
                resp = client.post(f"/api/credentials/{cred_id}/test", headers=headers)
                assert resp.status_code == 200, resp.text
                data = resp.json()["data"]
                assert data["ok"] is True
    finally:
        db.close()


@pytest.mark.asyncio
async def test_sweep_lock_skip_counts(client):
    """A row locked by a concurrent session is lock-skipped, not refreshed.

    With verify_missing=False it counts as skipped_unverified (honest, no
    guessing); with the default True it is verified as skipped_locked.
    Requires PostgreSQL row locking — skipped explicitly elsewhere so the
    test cannot vacuously pass on a non-locking backend.
    """
    from sqlalchemy import select

    user_info = register(client, email="sweep_lock@example.com")
    db = get_session()
    try:
        dialect = getattr(getattr(db.get_bind(), "dialect", None), "name", "")
    except Exception:
        dialect = ""
    if dialect != "postgresql":
        db.close()
        pytest.skip(f"requires postgres row locking (got {dialect!r})")
    locker = get_session()
    cred_id = f"cred-lock-{uuid.uuid4().hex[:8]}"
    try:
        db.add(Credential(
            id=cred_id,
            user_id=user_info["user"]["id"],
            name="Locked Google",
            type="google_calendar",
            data=encrypt_text(json.dumps({
                "access_token": "tok",
                "refresh_token": "rt",
                "expires_at": time.time() + 300,
            })),
        ))
        db.commit()
        # Hold the row lock in a second session (simulates a concurrent sweeper).
        locker.execute(select(Credential).where(Credential.id == cred_id).with_for_update())

        unverified = await auto_refresh_all_expiring_credentials(
            db, window_minutes=30, batch_size=10, verify_missing=False)
        assert unverified["skipped_unverified"] == 1
        assert unverified["skipped_locked"] == 0
        assert unverified["skipped"] == 1
        assert unverified["refreshed"] == 0

        verified = await auto_refresh_all_expiring_credentials(
            db, window_minutes=30, batch_size=10, verify_missing=True)
        assert verified["skipped_locked"] == 1
        assert verified["skipped_deleted"] == 0
        assert verified["skipped_unverified"] == 0
        assert verified["skipped"] == 1
    finally:
        locker.rollback()
        locker.close()
        db.close()
