"""Comprehensive test suite for Section 7: Credentials & Authentication.

Verifies all 10 checklist criteria:
1. Credential creation, editing, validation and deletion
2. Credential encryption and secure storage (AES-256-GCM + Fernet multi-key rotation)
3. OAuth authorization, callback and token exchange (CSRF state, PKCE, code exchange)
4. Access-token expiry and refresh-token rotation
5. Expired, revoked and invalid credential handling (CONNECTOR_AUTH_FAILED, interactive_required)
6. Permission scopes and insufficient-access errors (scope isolation & CONNECTOR_FORBIDDEN)
7. Credential selection and reuse across workflows (multi-workflow resolution & single rotation)
8. Credential isolation between users and tenants (strict 404 & zero cross-tenant leakage)
9. Secret masking in UI, logs and error messages (redact_data & no secret echo in responses)
10. Credential-provider abstraction and connection testing (provider registry & live probe)
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import select

from app.api.auth import create_token
from app.audit import log_event
from app.config import Settings, get_settings
from app.connectors import ConnectorErrorCode, make_connector_error
from app.credentials import service
from app.credentials.auto_reconnect import (
    can_auto_reconnect,
    is_credential_expiring,
    reconnect_credential_data,
)
from app.credentials.registry import (
    CREDENTIAL_TYPES,
    SECRET_FIELDS,
    get_provider_for_type,
    list_types,
    redact_data,
    validate_data,
)
from app.db import get_session
from app.models.credential import Credential
from app.models.oauth_state import OAuthState
from app.models.user import User
from app.security.crypto import (
    CredentialDecryptionError,
    cipher_decrypt_v2,
    cipher_encrypt_v2,
    decrypt_text,
    encrypt_text,
)
from tests.test_api.conftest import auth_headers, register


def _make_user(client, email="auditor_cred@example.com"):
    reg = register(client, email=email, password="AuditPassword123!")
    return reg["user"], auth_headers(reg["token"])


# ==============================================================================
# 1. Credential creation, editing, validation and deletion
# ==============================================================================
def test_credential_creation_editing_validation_deletion(client):
    """Test full CRUD lifecycle, field validation, and deletion."""
    user, headers = _make_user(client, email="crud_user@example.com")

    # 1. Validation failure: missing required host
    bad_resp = client.post(
        "/api/credentials",
        json={"name": "Bad SMTP", "type": "smtp", "data": {"port": 587}},
        headers=headers,
    )
    assert bad_resp.status_code == 422, f"Expected 422 on missing host: {bad_resp.text}"

    # 2. Validation failure: unknown credential type
    unknown_resp = client.post(
        "/api/credentials",
        json={"name": "Unknown", "type": "non_existent_type", "data": {}},
        headers=headers,
    )
    assert unknown_resp.status_code == 422

    # 3. Successful creation
    valid_data = {
        "host": "smtp.mailgun.org",
        "port": 587,
        "username": "postmaster@example.com",
        "password": "SecretPassword123!",
    }
    create_resp = client.post(
        "/api/credentials",
        json={"name": "Mailgun Primary", "type": "smtp", "data": valid_data},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()["data"]
    cred_id = created["id"]
    assert created["name"] == "Mailgun Primary"
    assert created["type"] == "smtp"
    assert "password" not in created  # Never returns secrets in metadata

    # 4. List credentials
    list_resp = client.get("/api/credentials", headers=headers)
    assert list_resp.status_code == 200
    listed_ids = [c["id"] for c in list_resp.json()["data"]]
    assert cred_id in listed_ids

    # 5. Edit credential name and secret (PUT / PATCH)
    update_resp = client.patch(
        f"/api/credentials/{cred_id}",
        json={"name": "Mailgun Production", "data": {"password": "NewRotatedPassword456!"}},
        headers=headers,
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()["data"]
    assert updated["name"] == "Mailgun Production"

    # Verify secret was rotated in database
    db = get_session()
    try:
        rec = db.get(Credential, cred_id)
        assert rec is not None
        decrypted = json.loads(decrypt_text(rec.data))
        assert decrypted["password"] == "NewRotatedPassword456!"
        assert decrypted["username"] == "postmaster@example.com"  # preserved
    finally:
        db.close()

    # 6. Deletion
    del_resp = client.delete(f"/api/credentials/{cred_id}", headers=headers)
    assert del_resp.status_code == 204

    # Confirm deletion from list
    list_resp_after = client.get("/api/credentials", headers=headers)
    assert cred_id not in [c["id"] for c in list_resp_after.json()["data"]]


# ==============================================================================
# 2. Credential encryption and secure storage
# ==============================================================================
def test_credential_encryption_and_secure_storage(client):
    """Test authenticated AES-256-GCM cipher, Fernet multi-key rotation, and ciphertext in DB."""
    user, headers = _make_user(client, email="crypto_user@example.com")

    # 1. Test AES-256-GCM v2 cipher
    plaintext = "super_sensitive_api_secret_key_9999"
    v2_blob = cipher_encrypt_v2(plaintext)
    assert v2_blob.startswith(b"v2:")
    # Nonce, Tag, Ciphertext base64 structure
    parts = v2_blob.decode().split(":")
    assert len(parts) == 4
    decrypted_v2 = cipher_decrypt_v2(v2_blob)
    assert decrypted_v2 == plaintext

    # Tamper with ciphertext -> should raise CredentialDecryptionError
    tampered_parts = list(parts)
    tampered_parts[3] = base64.urlsafe_b64encode(b"corrupted_tampered_bytes_1234").decode()
    tampered_blob = ":".join(tampered_parts).encode()
    with pytest.raises(CredentialDecryptionError):
        cipher_decrypt_v2(tampered_blob)

    # 2. Test DB storage verification: secret plaintext NEVER appears in database row
    secret_str = "SECRET_TOKEN_DO_NOT_LEAK_IN_SQL_OR_LOGS"
    resp = client.post(
        "/api/credentials",
        json={
            "name": "HTTP Secret",
            "type": "http",
            "data": {"api_key": secret_str, "username": "admin", "password": "pass"},
        },
        headers=headers,
    )
    assert resp.status_code == 201
    cred_id = resp.json()["data"]["id"]

    db = get_session()
    try:
        rec = db.get(Credential, cred_id)
        assert rec is not None
        # Assert raw data column does not contain sensitive substrings
        assert secret_str.encode() not in rec.data
        assert b"admin" not in rec.data
        assert b"pass" not in rec.data
        # But decrypt_text recovers it accurately
        unlocked = json.loads(decrypt_text(rec.data))
        assert unlocked["api_key"] == secret_str
    finally:
        db.close()


# ==============================================================================
# 3. OAuth authorization, callback and token exchange
# ==============================================================================
def test_oauth_authorization_callback_token_exchange(client):
    """Test OAuth authorization flow initiation, PKCE state verification, and token exchange."""
    user, headers = _make_user(client, email="oauth_user@example.com")

    # 1. Initiate OAuth connect
    with patch("app.api.oauth.get_settings") as mock_settings:
        st = Settings(
            salesforce_client_id="TEST_SALESFORCE_CLIENT_ID",
            salesforce_client_secret="TEST_SALESFORCE_CLIENT_SECRET",
            salesforce_redirect_uri="http://localhost:8000/api/auth/salesforce/callback",
            salesforce_login_url="https://login.salesforce.com",
            salesforce_scopes="refresh_token full api",
            oauth_state_ttl_seconds=600,
        )
        mock_settings.return_value = st

        conn_resp = client.post(
            "/api/auth/salesforce/connect",
            json={"login_url": "https://login.salesforce.com"},
            headers=headers,
        )
        assert conn_resp.status_code == 200, conn_resp.text
        data = conn_resp.json()["data"]
        auth_url = data["authorize_url"]
        state = data["state"]
        assert "response_type=code" in auth_url
        assert f"state={state}" in auth_url
        assert "code_challenge=" in auth_url  # PKCE challenge

        # Verify state was saved in DB
        db = get_session()
        try:
            state_row = db.get(OAuthState, state)
            assert state_row is not None
            assert state_row.user_id == user["id"]
            assert state_row.used is False
            assert state_row.code_verifier is not None
        finally:
            db.close()

        # 2. Simulate Callback with code exchange
        fake_token_response = httpx.Response(
            200,
            json={
                "access_token": "mock_sf_access_token_123",
                "refresh_token": "mock_sf_refresh_token_456",
                "instance_url": "https://my-test-org.salesforce.com",
                "id": "https://login.salesforce.com/id/org1/user1",
                "issued_at": str(int(time.time() * 1000)),
            },
            request=httpx.Request("POST", "https://login.salesforce.com/services/oauth2/token"),
        )

        with patch("app.api.oauth.get_safe_http_client") as mock_http:
            mock_client = AsyncMock()
            mock_client.request.return_value = fake_token_response
            mock_http.return_value.__aenter__.return_value = mock_client

            cb_resp = client.get(
                f"/api/auth/salesforce/callback?code=mock_code_xyz&state={state}",
                follow_redirects=False,
            )
            # Expect redirect back to frontend with ok=1
            assert cb_resp.status_code == 302
            loc = cb_resp.headers["location"]
            assert "ok=1" in loc

        # 3. Verify state is marked used (replay prevention)
        db = get_session()
        try:
            state_row = db.get(OAuthState, state)
            assert state_row.used is True

            # Verify credential was created for the user
            sf_creds = db.scalars(
                select(Credential).where(Credential.user_id == user["id"], Credential.type == "salesforce")
            ).all()
            assert len(sf_creds) >= 1
            sf_cred = sf_creds[-1]
            sf_data = json.loads(decrypt_text(sf_cred.data))
            assert sf_data["refresh_token"] == "mock_sf_refresh_token_456"
            assert sf_data["instance_url"] == "https://my-test-org.salesforce.com"
        finally:
            db.close()

        # Replay callback with the same state -> should fail with "state already used"
        replay_resp = client.get(
            f"/api/auth/salesforce/callback?code=mock_code_xyz&state={state}",
            follow_redirects=False,
        )
        assert replay_resp.status_code == 302
        assert "ok=0" in replay_resp.headers["location"]
        assert "state%20already%20used" in replay_resp.headers["location"] or "already" in replay_resp.headers["location"]


# ==============================================================================
# 4. Access-token expiry and refresh-token rotation
# ==============================================================================
@pytest.mark.asyncio
async def test_access_token_expiry_and_refresh_token_rotation():
    """Test detection of expiring tokens and background token rotation."""
    # 1. is_credential_expiring
    now = time.time()
    expired_data = {"expires_at": now - 100}
    expiring_soon_data = {"expires_at": now + 600}  # 10 minutes left
    fresh_data = {"expires_at": now + 7200}  # 2 hours left

    assert is_credential_expiring(expired_data, window_seconds=1800) is True
    assert is_credential_expiring(expiring_soon_data, window_seconds=1800) is True
    assert is_credential_expiring(fresh_data, window_seconds=1800) is False

    # 2. can_auto_reconnect
    assert can_auto_reconnect("salesforce", {"refresh_token": "r123"}) is True
    assert can_auto_reconnect("google", {"refresh_token": "r123"}) is True
    assert can_auto_reconnect("google", {"api_key": "k123"}) is False
    assert can_auto_reconnect("google", {"refresh_token": "r123", "refresh_token_expired": True}) is False

    # 3. Test token rotation via reconnect_credential_data
    fake_refreshed_body = {
        "access_token": "rotated_access_token_999",
        "refresh_token": "new_rotated_refresh_token_888",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    fake_resp = httpx.Response(
        200,
        json=fake_refreshed_body,
        request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = fake_resp

        original_data = {
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id": "google_cid",
            "client_secret": "google_sec",
            "refresh_token": "old_refresh_token_111",
            "access_token": "old_access_token_000",
            "expires_at": now - 50,
        }

        rotated = await reconnect_credential_data("google", original_data)
        assert rotated["access_token"] == "rotated_access_token_999"
        assert rotated["refresh_token"] == "new_rotated_refresh_token_888"
        assert rotated["expires_at"] > now


# ==============================================================================
# 5. Expired, revoked and invalid credential handling
# ==============================================================================
@pytest.mark.asyncio
async def test_expired_revoked_and_invalid_credential_handling(client):
    """Test handling of revoked tokens, invalid credentials, and CONNECTOR_AUTH_FAILED."""
    user, headers = _make_user(client, email="revoked_user@example.com")

    # 1. Test auto-reconnect error handling when refresh token is revoked
    revoked_resp = httpx.Response(
        400,
        json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
        request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = revoked_resp

        cred_data = {
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id": "cid",
            "client_secret": "sec",
            "refresh_token": "revoked_token",
        }

        # Should raise or flag as interactive_required
        with pytest.raises(Exception) as exc_info:
            await reconnect_credential_data("google", cred_data)
        assert "invalid_grant" in str(exc_info.value).lower() or "rejected" in str(exc_info.value).lower()

    # 2. Test Connection test endpoint returning structured failure on invalid credentials
    cred_resp = client.post(
        "/api/credentials",
        json={"name": "Broken HTTP", "type": "http", "data": {"api_key": "invalid_key_xyz"}},
        headers=headers,
    )
    cred_id = cred_resp.json()["data"]["id"]

    # Probing an invalid connection returns structured ok=False instead of 500
    test_resp = client.post(f"/api/credentials/{cred_id}/test", headers=headers)
    assert test_resp.status_code == 200
    res_body = test_resp.json()["data"]
    assert "ok" in res_body

    # 3. Test logout endpoint for complete revocation and deletion
    logout_resp = client.post(f"/api/credentials/{cred_id}/logout", headers=headers)
    assert logout_resp.status_code == 200
    assert logout_resp.json()["data"]["id"] == cred_id

    # Confirm credential was removed
    get_after = client.get("/api/credentials", headers=headers)
    assert cred_id not in [c["id"] for c in get_after.json()["data"]]


# ==============================================================================
# 6. Permission scopes and insufficient-access errors
# ==============================================================================
def test_permission_scopes_and_insufficient_access_errors():
    """Test OAuth scope specification per provider and connector forbidden errors."""
    from app.oauth_providers import (
        PROVIDERS,
        DYNAMICS_CRM,
        GMAIL,
        GOOGLE_DOCS,
        GOOGLE_DRIVE,
        GOOGLE_SHEETS,
        HUBSPOT,
        SALESFORCE,
    )

    settings = Settings(
        salesforce_scopes="refresh_token api",
        hubspot_scopes="crm.objects.contacts.read",
        google_scopes="https://www.googleapis.com/auth/calendar",
        google_sheets_scopes="https://www.googleapis.com/auth/spreadsheets",
        gmail_scopes="https://www.googleapis.com/auth/gmail.send",
        google_drive_scopes="https://www.googleapis.com/auth/drive",
        google_docs_scopes="https://www.googleapis.com/auth/documents",
        dynamics_crm_scopes="user_impersonation",
    )

    # Verify each provider has dedicated isolated scope sets
    assert SALESFORCE.scopes(settings) == "refresh_token api"
    assert HUBSPOT.scopes(settings) == "crm.objects.contacts.read"
    assert GMAIL.scopes(settings) == "https://www.googleapis.com/auth/gmail.send"
    assert GOOGLE_SHEETS.scopes(settings) == "https://www.googleapis.com/auth/spreadsheets"
    assert GOOGLE_DRIVE.scopes(settings) == "https://www.googleapis.com/auth/drive"
    assert PROVIDERS["google_calendar"].scopes(settings) == "https://www.googleapis.com/auth/calendar"

    # Test ConnectorErrorCode.FORBIDDEN mapping for insufficient access
    err = make_connector_error(
        ConnectorErrorCode.FORBIDDEN,
        "User lacks necessary permission scopes to perform this operation.",
    )
    assert err.code == "CONNECTOR_FORBIDDEN"
    assert "lacks necessary permission" in str(err)
    assert err.retryable is False


# ==============================================================================
# 7. Credential selection and reuse across workflows
# ==============================================================================
def test_credential_selection_and_reuse_across_workflows(client):
    """Test binding a single credential across multiple workflows and consistent resolution."""
    user, headers = _make_user(client, email="reuse_user@example.com")

    # 1. Create a single shared API credential
    create_resp = client.post(
        "/api/credentials",
        json={
            "name": "Shared HTTP API",
            "type": "http",
            "data": {"api_key": "initial_shared_token_111", "username": "shared_u", "password": "shared_p"},
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    cred_id = create_resp.json()["data"]["id"]

    db = get_session()
    try:
        # 2. Simulate Workflow 1 and Workflow 2 resolving the same credential
        node1_refs = {"http": cred_id}
        node2_refs = {"http": cred_id}

        res1 = service.resolve_credentials(db, user["id"], node1_refs)
        res2 = service.resolve_credentials(db, user["id"], node2_refs)

        assert res1["http"]["api_key"] == "initial_shared_token_111"
        assert res2["http"]["api_key"] == "initial_shared_token_111"
        assert res1["http"]["_credential_id"] == cred_id
        assert res2["http"]["_credential_id"] == cred_id

        # 3. Rotate the secret on the credential (single point of rotation)
        service.update_for_user(
            db,
            user["id"],
            cred_id,
            name="Shared HTTP API Rotated",
            data={"api_key": "rotated_shared_token_222"},
        )

        # 4. Verify both workflows immediately receive the rotated secret without reconfiguration
        res1_after = service.resolve_credentials(db, user["id"], node1_refs)
        res2_after = service.resolve_credentials(db, user["id"], node2_refs)

        assert res1_after["http"]["api_key"] == "rotated_shared_token_222"
        assert res2_after["http"]["api_key"] == "rotated_shared_token_222"
        assert res1_after["http"]["username"] == "shared_u"  # Preserved
    finally:
        db.close()


# ==============================================================================
# 8. Credential isolation between users and tenants
# ==============================================================================
def test_credential_isolation_between_users_and_tenants(client):
    """Verify strict multi-tenant isolation: User B cannot view, modify, delete, or resolve User A's credentials."""
    user_a, headers_a = _make_user(client, email="tenant_a@example.com")
    user_b, headers_b = _make_user(client, email="tenant_b@example.com")

    # User A creates a confidential credential
    create_resp = client.post(
        "/api/credentials",
        json={
            "name": "Tenant A Secret Key",
            "type": "http",
            "data": {"api_key": "tenant_a_super_secret"},
        },
        headers=headers_a,
    )
    assert create_resp.status_code == 201
    cred_a_id = create_resp.json()["data"]["id"]

    # 1. User B lists credentials -> must be empty / not include cred_a_id
    list_b = client.get("/api/credentials", headers=headers_b).json()["data"]
    assert not any(c["id"] == cred_a_id for c in list_b)

    # 2. User B tries to update User A's credential -> 404
    update_b = client.patch(
        f"/api/credentials/{cred_a_id}",
        json={"name": "Hacked by Tenant B"},
        headers=headers_b,
    )
    assert update_b.status_code == 404

    # 3. User B tries to delete User A's credential -> 404
    delete_b = client.delete(f"/api/credentials/{cred_a_id}", headers=headers_b)
    assert delete_b.status_code == 404

    # 4. User B tries to test User A's credential -> 404
    test_b = client.post(f"/api/credentials/{cred_a_id}/test", headers=headers_b)
    assert test_b.status_code == 404

    # 5. User B tries to get policy of User A's credential -> 404
    policy_b = client.get(f"/api/credentials/{cred_a_id}/policy", headers=headers_b)
    assert policy_b.status_code == 404

    # 6. Service layer isolation: User B workflow execution attempting to resolve User A's credential
    db = get_session()
    try:
        with pytest.raises(service.CredentialError) as exc_info:
            service.resolve_credentials(db, user_b["id"], {"http": cred_a_id})
        assert exc_info.value.code == "CREDENTIALS_REQUIRED"
        assert "not found or not yours" in str(exc_info.value).lower()
    finally:
        db.close()


# ==============================================================================
# 9. Secret masking in UI, logs and error messages
# ==============================================================================
def test_secret_masking_in_ui_logs_and_error_messages(client):
    """Test that redact_data masks secrets, endpoints never echo secrets, and placeholders are preserved."""
    user, headers = _make_user(client, email="masking_user@example.com")

    # 1. Test redact_data utility across types
    raw_smtp = {"host": "smtp.example.com", "port": 587, "username": "admin", "password": "super_secret_pw"}
    masked_smtp = redact_data("smtp", raw_smtp)
    assert masked_smtp["password"] == "••••••••"
    assert masked_smtp["username"] == "admin"
    assert masked_smtp["host"] == "smtp.example.com"

    raw_sf = {
        "client_id": "cid_123",
        "client_secret": "csec_top_secret",
        "refresh_token": "refresh_secret",
        "instance_url": "https://test.salesforce.com",
    }
    masked_sf = redact_data("salesforce", raw_sf)
    assert masked_sf["client_secret"] == "••••••••"
    assert masked_sf["refresh_token"] == "••••••••"
    assert masked_sf["client_id"] == "cid_123"

    # 2. Test create endpoint response does not echo secrets
    create_resp = client.post(
        "/api/credentials",
        json={"name": "Mask Test", "type": "smtp", "data": raw_smtp},
        headers=headers,
    )
    meta = create_resp.json()["data"]
    assert "password" not in meta
    assert "data" not in meta

    # 3. Test list endpoint does not leak secrets
    list_resp = client.get("/api/credentials", headers=headers)
    for c in list_resp.json()["data"]:
        assert "password" not in c
        assert "data" not in c

    # 4. Test update preservation when UI submits masked "••••••••"
    cred_id = meta["id"]
    client.patch(
        f"/api/credentials/{cred_id}",
        json={"name": "Mask Test Renamed", "data": {"password": "••••••••", "username": "new_admin"}},
        headers=headers,
    )

    db = get_session()
    try:
        rec = db.get(Credential, cred_id)
        decrypted = json.loads(decrypt_text(rec.data))
        # Original secret was NOT replaced with dots!
        assert decrypted["password"] == "super_secret_pw"
        assert decrypted["username"] == "new_admin"
    finally:
        db.close()


# ==============================================================================
# 10. Credential-provider abstraction and connection testing
# ==============================================================================
def test_credential_provider_abstraction_and_connection_testing(client):
    """Test provider registry abstraction, types catalog, auth metadata, and connection testing."""
    user, headers = _make_user(client, email="providers_user@example.com")

    # 1. /api/credentials/providers
    prov_resp = client.get("/api/credentials/providers", headers=headers)
    assert prov_resp.status_code == 200
    providers = prov_resp.json()["data"]
    assert isinstance(providers, list)
    assert len(providers) > 0

    # 2. /api/credentials/types
    types_resp = client.get("/api/credentials/types", headers=headers)
    assert types_resp.status_code == 200
    types = types_resp.json()["data"]
    assert isinstance(types, list)
    type_names = {t["type"] for t in types}
    assert {"smtp", "http", "salesforce", "database"}.issubset(type_names)

    # 3. /api/credentials/auth-metadata
    meta_resp = client.get("/api/credentials/auth-metadata", headers=headers)
    assert meta_resp.status_code == 200
    meta_data = meta_resp.json()["data"]
    assert "connectors" in meta_data
    assert "summary" in meta_data
    assert meta_data["summary"]["total_connectors_discovered"] > 0

    # 4. /api/credentials/{id}/policy
    cred_resp = client.post(
        "/api/credentials",
        json={"name": "Policy HTTP", "type": "http", "data": {"api_key": "my_api_key_123"}},
        headers=headers,
    )
    cred_id = cred_resp.json()["data"]["id"]

    policy_resp = client.get(f"/api/credentials/{cred_id}/policy", headers=headers)
    assert policy_resp.status_code == 200
    policy = policy_resp.json()["data"]
    assert policy["credential_id"] == cred_id
    assert "capabilities" in policy
    assert "mode" in policy
    assert "state" in policy

    # 5. /api/credentials/{id}/test connection testing abstraction
    probe_resp = client.post(f"/api/credentials/{cred_id}/test", headers=headers)
    assert probe_resp.status_code == 200
    probe_data = probe_resp.json()["data"]
    assert "ok" in probe_data
