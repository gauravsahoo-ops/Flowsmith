"""Acceptance tests for Token Fetch Node and Token Store Node.

Covers all 10 core acceptance requirements:
- TEST 1: First Run (MISSING / requiresAuthentication=True) -> Token Store saves credentials
- TEST 2: Second Run (reused without Login API)
- TEST 3: Multiple Runs (15+ executions with 0 redundant logins)
- TEST 4: Access Token Expired (automatic single-flight refresh, rotation preserved)
- TEST 5: Refresh Token Invalid (fails cleanly to REAUTH_REQUIRED without crash)
- TEST 6: No Refresh Token (skips refresh call directly to REAUTH_REQUIRED)
- TEST 7: API Returns 401 (single retry with refreshed token; loop protection against infinite retries)
- TEST 8: Duplicate Prevention (UPSERT guarantees 1 record per workflow+provider)
- TEST 9: Concurrent Execution (single-flight locking prevents duplicate refreshes)
- TEST 10: Security (credentials encrypted at rest, masked in logs, safe errors)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
import pytest
from sqlalchemy import select

from app.db import get_session
from app.engine.node_base import MemoryKVStore, NodeContext
from app.models.user import User
from app.models.workflow import WorkflowRecord
from app.models.workflow_auth import WorkflowAuthState
from app.nodes.token_fetch import TokenFetchNode, TokenFetchParams
from app.nodes.token_store import TokenStoreNode, TokenStoreParams
from app.nodes.http_request import HTTPRequestNode, HTTPRequestParams
from app.security.crypto import decrypt_text


def _ctx(workflow_id="wf_token_test"):
    return NodeContext(
        execution_id=f"exec_{uuid.uuid4().hex[:8]}",
        workflow_id=workflow_id,
        logger=logging.getLogger("test_tokens"),
        http_client=None,
        storage=MemoryKVStore(),
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _setup_workflow_row():
    """Ensure parent workflow and user records exist for foreign key constraint."""
    db = get_session()
    try:
        user = User(email=f"token_test_{uuid.uuid4().hex[:8]}@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        db.add(
            WorkflowRecord(
                id="wf_token_test",
                user_id=user.id,
                name="Token Test Workflow",
                data={"id": "wf_token_test", "name": "Token Test", "nodes": [], "connections": []},
            )
        )
        db.commit()
        yield
    finally:
        db.close()


def _store(
    workflow_id="wf_token_test",
    provider="salesforce",
    access_token="initial_access_tok",
    refresh_token="initial_refresh_tok",
    **kw,
):
    params = {
        "workflow_id": workflow_id,
        "provider": provider,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_url": "https://login.salesforce.com/services/oauth2/token",
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "expires_at": time.time() + 3600,
    }
    params.update(kw)
    node = TokenStoreNode()
    return _run(node.run(_ctx(workflow_id), TokenStoreParams(**params), []))


def _fetch(workflow_id="wf_token_test", provider="salesforce", **kw):
    params = {"workflow_id": workflow_id, "provider": provider}
    params.update(kw)
    node = TokenFetchNode()
    return _run(node.run(_ctx(workflow_id), TokenFetchParams(**params), []))


# ==============================================================================
# TEST 1 — FIRST RUN
# ==============================================================================
def test_acceptance_1_first_run():
    """First run: no stored credentials -> requiresAuthentication=True.
    Then Login API result is passed to Token Store -> saved successfully.
    """
    fetch_out = _fetch().output_items[0]
    assert fetch_out["status"] == "MISSING"
    assert fetch_out["requiresAuthentication"] is True
    assert fetch_out["isValid"] is False
    assert fetch_out["accessToken"] is None
    assert fetch_out["refreshToken"] is None
    assert fetch_out["workflowId"] == "wf_token_test"
    assert fetch_out["provider"] == "salesforce"

    # Simulated Login API / HTTP Auth returns tokens -> pass to Token Store
    store_out = _store(access_token="tok_after_login", refresh_token="ref_after_login").output_items[0]
    assert store_out["saved"] is True
    assert store_out["updated"] is False  # Created on first run
    assert store_out["accessToken"] == "tok_after_login"
    assert store_out["refreshToken"] == "ref_after_login"
    assert store_out["isValid"] is True
    assert store_out["requiresAuthentication"] is False


# ==============================================================================
# TEST 2 — SECOND RUN
# ==============================================================================
def test_acceptance_2_second_run():
    """Second run: valid credentials exist -> fetched and reused.
    Login API is NOT called.
    """
    _store(access_token="valid_stored_token", refresh_token="valid_refresh_token")

    fetch_out = _fetch().output_items[0]
    assert fetch_out["status"] == "VALID"
    assert fetch_out["isValid"] is True
    assert fetch_out["requiresAuthentication"] is False
    assert fetch_out["accessToken"] == "valid_stored_token"
    assert fetch_out["refreshToken"] == "valid_refresh_token"
    assert fetch_out["source"] == "stored_credentials"


# ==============================================================================
# TEST 3 — MULTIPLE RUNS (15+ executions)
# ==============================================================================
def test_acceptance_3_multiple_runs_reuse_credentials():
    """Run workflow 15 times with valid credentials -> same stored tokens reused every time."""
    _store(access_token="reusable_token_xyz", refresh_token="reusable_refresh_xyz")

    for i in range(15):
        out = _fetch().output_items[0]
        assert out["status"] == "VALID"
        assert out["isValid"] is True
        assert out["requiresAuthentication"] is False
        assert out["accessToken"] == "reusable_token_xyz"


# ==============================================================================
# TEST 4 — ACCESS TOKEN EXPIRED + REFRESH TOKEN AVAILABLE
# ==============================================================================
def test_acceptance_4_access_token_expired_refreshes_automatically(monkeypatch):
    """Expired access token + valid refresh token -> Token Fetch triggers provider refresh,
    persists new access token, preserves refresh token, and returns valid token.
    """
    _store(access_token="old_expired_tok", refresh_token="original_refresh_tok", expires_at=time.time() - 200)

    calls = []
    from app.auth_state import adapter

    async def fake_refresh(self, bundle):
        calls.append(dict(bundle))
        # Simulated provider returns fresh access token (without rotating refresh token)
        return {"access_token": "fresh_access_tok_456", "expires_at": time.time() + 7200}

    monkeypatch.setattr(adapter.OAuthManager, "refresh", fake_refresh)

    out = _fetch().output_items[0]
    assert out["status"] == "REFRESHED"
    assert out["isValid"] is True
    assert out["requiresAuthentication"] is False
    assert out["accessToken"] == "fresh_access_tok_456"
    assert out["refreshToken"] == "original_refresh_tok"  # Preserved
    assert len(calls) == 1

    # Next execution immediately sees VALID without calling refresh again
    next_out = _fetch().output_items[0]
    assert next_out["status"] == "VALID"
    assert next_out["accessToken"] == "fresh_access_tok_456"
    assert len(calls) == 1


# ==============================================================================
# TEST 5 — REFRESH TOKEN INVALID / REFRESH FAILS
# ==============================================================================
def test_acceptance_5_refresh_fails_falls_back_to_reauth(monkeypatch):
    """Expired access token + refresh attempt fails -> falls back to REAUTH_REQUIRED,
    prompting downstream workflow to call Login API.
    """
    _store(access_token="expired_tok", refresh_token="invalid_refresh_tok", expires_at=time.time() - 200)

    from app.auth_state import adapter

    async def fake_refresh_error(self, bundle):
        raise ValueError("Invalid refresh token (expired grant)")

    monkeypatch.setattr(adapter.OAuthManager, "refresh", fake_refresh_error)

    out = _fetch().output_items[0]
    assert out["status"] == "REAUTH_REQUIRED"
    assert out["requiresAuthentication"] is True
    assert out["isValid"] is False


# ==============================================================================
# TEST 6 — NO REFRESH TOKEN
# ==============================================================================
def test_acceptance_6_no_refresh_token_skips_refresh_to_reauth(monkeypatch):
    """Expired access token without a refresh token -> goes directly to REAUTH_REQUIRED
    without attempting a network refresh call.
    """
    _store(access_token="expired_tok", refresh_token="", expires_at=time.time() - 200)

    calls = []
    from app.auth_state import adapter

    async def fake_refresh(self, bundle):
        calls.append(bundle)
        return {"access_token": "should_not_be_called"}

    monkeypatch.setattr(adapter.OAuthManager, "refresh", fake_refresh)

    out = _fetch().output_items[0]
    assert out["status"] == "REAUTH_REQUIRED"
    assert out["requiresAuthentication"] is True
    assert calls == []


# ==============================================================================
# TEST 7 — API RETURNS 401 & LOOP PROTECTION
# ==============================================================================
def test_acceptance_7_api_401_recovery_and_loop_protection(monkeypatch):
    """When external API returns 401:
    - HTTPRequestNode attempts token refresh from stored workflow auth
    - Retries request once
    - Enforces loop protection (does not loop infinitely; raises safe AUTH_UNAUTHORIZED)
    """
    _store(access_token="stale_api_tok", refresh_token="valid_refresh_tok")

    from app.auth_state import adapter
    refresh_calls = []

    async def fake_refresh(self, bundle):
        refresh_calls.append(dict(bundle))
        return {"access_token": "recovered_token_123", "expires_at": time.time() + 3600}

    monkeypatch.setattr(adapter.OAuthManager, "refresh", fake_refresh)

    request_attempts = []

    # Mock _do_request to return 401 on first attempt, 200 on retry with new token
    async def fake_do_request(self, ctx, params, url, headers, query, json_body, data, files):
        auth_hdr = headers.get("Authorization", "")
        request_attempts.append(auth_hdr)
        import httpx
        if "recovered_token_123" in auth_hdr:
            return httpx.Response(200, json={"success": True}, request=httpx.Request("GET", url))
        return httpx.Response(401, json={"error": "invalid_token"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(HTTPRequestNode, "_do_request", fake_do_request)

    http_node = HTTPRequestNode()
    http_params = HTTPRequestParams(url="https://api.example.com/data", method="GET")
    result = _run(http_node.run(_ctx("wf_token_test"), http_params, []))

    assert result.output_items[0]["statusCode"] == 200
    assert len(refresh_calls) == 1
    assert len(request_attempts) == 2  # 1 initial + 1 retry


def test_acceptance_7_persistent_401_stops_without_infinite_loop(monkeypatch):
    """If 401 persists even after refresh, stops cleanly and raises AUTH_UNAUTHORIZED."""
    _store(access_token="stale_tok", refresh_token="valid_refresh_tok")

    from app.auth_state import adapter
    async def fake_refresh(self, bundle):
        return {"access_token": "token_still_rejected", "expires_at": time.time() + 3600}

    monkeypatch.setattr(adapter.OAuthManager, "refresh", fake_refresh)

    async def fake_always_401(self, ctx, params, url, headers, query, json_body, data, files):
        import httpx
        return httpx.Response(401, json={"error": "unauthorized"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(HTTPRequestNode, "_do_request", fake_always_401)

    from app.engine.errors import NodeExecutionError
    http_node = HTTPRequestNode()
    http_params = HTTPRequestParams(url="https://api.example.com/data", method="GET")

    with pytest.raises(NodeExecutionError) as exc_info:
        _run(http_node.run(_ctx("wf_token_test"), http_params, []))

    assert exc_info.value.code == "AUTH_UNAUTHORIZED"
    assert "Authentication failed" in str(exc_info.value.message)


# ==============================================================================
# TEST 8 — DUPLICATE PREVENTION (UPSERT)
# ==============================================================================
def test_acceptance_8_upsert_prevents_duplicates():
    """Running Token Store 5 times updates the same credential row without creating duplicates."""
    for i in range(5):
        out = _store(access_token=f"token_iteration_{i}", refresh_token=f"refresh_iteration_{i}").output_items[0]
        assert out["saved"] is True
        if i > 0:
            assert out["updated"] is True

    db = get_session()
    try:
        rows = db.scalars(
            select(WorkflowAuthState).where(
                WorkflowAuthState.workflow_id == "wf_token_test",
                WorkflowAuthState.provider == "salesforce",
            )
        ).all()
        # Exactly 1 row in the database
        assert len(rows) == 1
    finally:
        db.close()


# ==============================================================================
# TEST 9 — CONCURRENT EXECUTION SINGLE-FLIGHT LOCK
# ==============================================================================
def test_acceptance_9_concurrent_executions_single_refresh(monkeypatch):
    """5 concurrent executions with expired token execute exactly 1 refresh operation."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    _store(access_token="expired_tok", refresh_token="ref_tok", expires_at=time.time() - 200)

    lock = threading.Lock()
    refresh_counter = [0]

    from app.auth_state import adapter

    async def fake_slow_refresh(self, bundle):
        with lock:
            refresh_counter[0] += 1
        await asyncio.sleep(0.15)
        return {"access_token": "concurrent_fresh_tok", "expires_at": time.time() + 3600}

    monkeypatch.setattr(adapter.OAuthManager, "refresh", fake_slow_refresh)

    def worker_fetch():
        return _run(TokenFetchNode().run(_ctx("wf_token_test"), TokenFetchParams(provider="salesforce"), []))

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker_fetch) for _ in range(5)]
        results = [f.result() for f in futures]

    assert all(r.output_items[0]["isValid"] is True for r in results)
    assert all(r.output_items[0]["accessToken"] == "concurrent_fresh_tok" for r in results)
    # Single-flight: only 1 network refresh was executed
    assert refresh_counter[0] == 1


# ==============================================================================
# TEST 10 — SECURITY & SECRET HYGIENE
# ==============================================================================
def test_acceptance_10_security_and_secret_hygiene(caplog):
    """Verify secrets are encrypted at rest in DB and never exposed in plaintext."""
    secret_access = "super_secret_access_token_9999"
    secret_refresh = "super_secret_refresh_token_8888"

    _store(access_token=secret_access, refresh_token=secret_refresh)

    with caplog.at_level(logging.INFO, logger="test_tokens"):
        _fetch()

    # Log does not leak plaintext secrets
    assert secret_access not in caplog.text
    assert secret_refresh not in caplog.text

    # Database stores encrypted ciphertext, not plaintext
    db = get_session()
    try:
        row = db.scalar(
            select(WorkflowAuthState).where(WorkflowAuthState.workflow_id == "wf_token_test")
        )
        assert row is not None
        assert secret_access.encode() not in bytes(row.data)
        assert secret_refresh.encode() not in bytes(row.data)

        # Decrypts properly with encryption key
        import json
        decrypted = json.loads(decrypt_text(row.data))
        assert decrypted["access_token"] == secret_access
        assert decrypted["refresh_token"] == secret_refresh
    finally:
        db.close()


# ==============================================================================
# TEST 11 — AUTOMATIC TOKEN STORE (ZERO MAPPING)
# ==============================================================================
def test_acceptance_11_automatic_token_store_from_upstream():
    """Token Store automatically extracts access_token, refresh_token, and expires_in
    from the upstream Login API response item without requiring manual expressions.
    """
    upstream_item = {
        "statusCode": 200,
        "body": {
            "access_token": "auto_extracted_access_token_123",
            "refresh_token": "auto_extracted_refresh_token_456",
            "expires_in": 7200,
            "token_type": "Bearer",
        },
    }

    # Pass completely empty params with auto_detect=True
    node = TokenStoreNode()
    result = _run(node.run(_ctx("wf_token_test"), TokenStoreParams(provider="salesforce", auto_detect=True), [upstream_item]))

    out = result.output_items[0]
    assert out["saved"] is True
    assert out["autoDetected"] is True
    assert out["accessToken"] == "auto_extracted_access_token_123"
    assert out["refreshToken"] == "auto_extracted_refresh_token_456"

    # Token Fetch immediately finds it
    fetch_out = _fetch().output_items[0]
    assert fetch_out["status"] == "VALID"
    assert fetch_out["accessToken"] == "auto_extracted_access_token_123"
    assert fetch_out["refreshToken"] == "auto_extracted_refresh_token_456"


def test_acceptance_12_http_request_node_auto_store(monkeypatch):
    """HTTPRequestNode with auto_store_token=True automatically saves credentials upon login success."""
    async def fake_login_request(self, ctx, params, url, headers, query, json_body, data, files):
        import httpx
        return httpx.Response(
            200,
            json={"access_token": "login_api_direct_token_777", "refresh_token": "login_api_refresh_777", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(HTTPRequestNode, "_do_request", fake_login_request)

    http_node = HTTPRequestNode()
    http_params = HTTPRequestParams(
        url="https://login.example.com/oauth/token",
        method="POST",
        auto_store_token=True,
        auto_store_provider="salesforce",
    )
    _run(http_node.run(_ctx("wf_token_test"), http_params, []))

    # Token Fetch retrieves the auto-stored token
    fetch_out = _fetch().output_items[0]
    assert fetch_out["status"] == "VALID"
    assert fetch_out["accessToken"] == "login_api_direct_token_777"
    assert fetch_out["refreshToken"] == "login_api_refresh_777"
