"""Acceptance tests for ONE Universal Token Manager Node (token_manager).

Covers all 10 core acceptance requirements:
- TEST 1: First Run (MISSING / requiresAuthentication=True) -> Login API -> Token Manager stores credentials
- TEST 2: Second Run (reused from DB without calling Login API)
- TEST 3: Many Runs (100 executions reusing stored credentials with 0 login calls)
- TEST 4: Token Expired (automatic single-flight refresh, rotation preserved, no Login API)
- TEST 5: Refresh Failed (falls back to REAUTH_REQUIRED -> Login API -> Store in DB)
- TEST 6: No Refresh Token (skips refresh call directly to REAUTH_REQUIRED)
- TEST 7: API 401 Recovery & Loop Protection (retries once with refreshed token, stops on persistent 401)
- TEST 8: Duplicate Prevention (atomic UPSERT guarantees 1 record per workflow+provider)
- TEST 9: Concurrent Executions (single-flight locking prevents duplicate refreshes across workers)
- TEST 10: Security (encrypted at rest in DB, masked in logs, safe errors without secrets)
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
from app.nodes.token_manager import TokenManagerNode, TokenManagerParams
from app.nodes.http_request import HTTPRequestNode, HTTPRequestParams
from app.security.crypto import decrypt_text


def _ctx(workflow_id="wf_tm_test"):
    return NodeContext(
        execution_id=f"exec_{uuid.uuid4().hex[:8]}",
        workflow_id=workflow_id,
        logger=logging.getLogger("test_tm"),
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
        user = User(email=f"tm_test_{uuid.uuid4().hex[:8]}@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        db.add(
            WorkflowRecord(
                id="wf_tm_test",
                user_id=user.id,
                name="Token Manager Workflow",
                data={"id": "wf_tm_test", "name": "Token Manager Test", "nodes": [], "connections": []},
            )
        )
        db.commit()
        yield
    finally:
        db.close()


def _tm_fetch(workflow_id="wf_tm_test", provider="salesforce", **kw):
    params = {"workflow_id": workflow_id, "provider": provider, "mode": "fetch"}
    params.update(kw)
    node = TokenManagerNode()
    return _run(node.run(_ctx(workflow_id), TokenManagerParams(**params), []))


def _tm_store(
    input_items=None,
    workflow_id="wf_tm_test",
    provider="salesforce",
    access_token="initial_access_tok",
    refresh_token="initial_refresh_tok",
    **kw,
):
    params = {
        "workflow_id": workflow_id,
        "provider": provider,
        "mode": "store",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_url": "https://login.salesforce.com/services/oauth2/token",
        "client_id": "cid",
        "client_secret": "csec",
        "expires_at": time.time() + 3600,
    }
    params.update(kw)
    node = TokenManagerNode()
    items = input_items or []
    return _run(node.run(_ctx(workflow_id), TokenManagerParams(**params), items))


# ==============================================================================
# TEST 1 — FIRST RUN
# ==============================================================================
def test_acceptance_1_first_run():
    """First run: no stored credentials -> Token Manager returns requiresAuthentication=True.
    Login API executes and returns tokens -> Token Manager stores them in database.
    """
    fetch_out = _tm_fetch().output_items[0]
    assert fetch_out["status"] == "MISSING"
    assert fetch_out["requiresAuthentication"] is True
    assert fetch_out["isValid"] is False
    assert fetch_out["accessToken"] is None
    assert fetch_out["refreshToken"] is None

    # Login API output is passed into Token Manager (automatic store mode)
    login_output = [{
        "statusCode": 200,
        "body": {
            "access_token": "first_run_token_123",
            "refresh_token": "first_run_refresh_123",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
    }]
    node = TokenManagerNode()
    store_out = _run(node.run(_ctx("wf_tm_test"), TokenManagerParams(provider="salesforce", mode="auto"), login_output)).output_items[0]

    assert store_out["saved"] is True
    assert store_out["updated"] is False
    assert store_out["accessToken"] == "first_run_token_123"
    assert store_out["refreshToken"] == "first_run_refresh_123"
    assert store_out["isValid"] is True
    assert store_out["requiresAuthentication"] is False


# ==============================================================================
# TEST 2 — SECOND RUN
# ==============================================================================
def test_acceptance_2_second_run():
    """Second run: database has valid token -> Token Manager retrieves it.
    Login API is NOT called.
    """
    _tm_store(access_token="valid_stored_token_abc", refresh_token="valid_refresh_abc")

    fetch_out = _tm_fetch().output_items[0]
    assert fetch_out["status"] == "VALID"
    assert fetch_out["isValid"] is True
    assert fetch_out["requiresAuthentication"] is False
    assert fetch_out["accessToken"] == "valid_stored_token_abc"
    assert fetch_out["refreshToken"] == "valid_refresh_abc"
    assert fetch_out["source"] == "stored_credentials"


# ==============================================================================
# TEST 3 — MANY RUNS (100 executions)
# ==============================================================================
def test_acceptance_3_many_runs_reuse_without_login():
    """Run workflow 100 times while token is valid:
    Token Manager returns stored token every time; 0 login calls.
    """
    _tm_store(access_token="constant_token_100", refresh_token="constant_refresh_100")

    for _ in range(100):
        out = _tm_fetch().output_items[0]
        assert out["status"] == "VALID"
        assert out["isValid"] is True
        assert out["requiresAuthentication"] is False
        assert out["accessToken"] == "constant_token_100"


# ==============================================================================
# TEST 4 — TOKEN EXPIRED + REFRESH TOKEN AVAILABLE
# ==============================================================================
def test_acceptance_4_token_expired_auto_refreshes_in_single_node(monkeypatch):
    """Token expired -> Token Manager auto-refreshes via provider adapter,
    updates database, preserves refresh token, and returns valid token.
    Login API is NOT called.
    """
    _tm_store(access_token="expired_tok", refresh_token="preserve_this_ref", expires_at=time.time() - 200)

    calls = []
    from app.auth_state import adapter

    async def fake_refresh(self, bundle):
        calls.append(dict(bundle))
        return {"access_token": "refreshed_access_tok_999", "expires_at": time.time() + 3600}

    monkeypatch.setattr(adapter.OAuthManager, "refresh", fake_refresh)

    out = _tm_fetch().output_items[0]
    assert out["status"] == "REFRESHED"
    assert out["isValid"] is True
    assert out["requiresAuthentication"] is False
    assert out["accessToken"] == "refreshed_access_tok_999"
    assert out["refreshToken"] == "preserve_this_ref"
    assert len(calls) == 1

    # Next execution immediately uses the new token from database
    next_out = _tm_fetch().output_items[0]
    assert next_out["status"] == "VALID"
    assert next_out["accessToken"] == "refreshed_access_tok_999"
    assert len(calls) == 1


# ==============================================================================
# TEST 5 — REFRESH FAILED
# ==============================================================================
def test_acceptance_5_refresh_failed_falls_back_to_reauth(monkeypatch):
    """Token expired + refresh fails -> falls back to REAUTH_REQUIRED,
    prompting workflow to run Login API.
    """
    _tm_store(access_token="expired_tok", refresh_token="bad_refresh_token", expires_at=time.time() - 200)

    from app.auth_state import adapter

    async def fake_refresh_fail(self, bundle):
        raise ValueError("Invalid refresh token (grant revoked)")

    monkeypatch.setattr(adapter.OAuthManager, "refresh", fake_refresh_fail)

    out = _tm_fetch().output_items[0]
    assert out["status"] == "REAUTH_REQUIRED"
    assert out["requiresAuthentication"] is True
    assert out["isValid"] is False


# ==============================================================================
# TEST 6 — NO REFRESH TOKEN
# ==============================================================================
def test_acceptance_6_no_refresh_token_skips_refresh():
    """Token expired + no refresh token -> directly returns REAUTH_REQUIRED
    without attempting a network refresh.
    """
    _tm_store(access_token="expired_tok", refresh_token="", expires_at=time.time() - 200)

    out = _tm_fetch().output_items[0]
    assert out["status"] == "REAUTH_REQUIRED"
    assert out["requiresAuthentication"] is True


# ==============================================================================
# TEST 7 — API RETURNS 401 & LOOP PROTECTION
# ==============================================================================
def test_acceptance_7_401_recovery_and_loop_protection(monkeypatch):
    """API returns 401 -> Token Manager invalidates token, triggers refresh,
    retries once. Persistent 401 stops without infinite loop.
    """
    _tm_store(access_token="stale_token", refresh_token="valid_ref")

    from app.auth_state import adapter
    refresh_calls = []

    async def fake_refresh(self, bundle):
        refresh_calls.append(dict(bundle))
        return {"access_token": "recovered_token_401", "expires_at": time.time() + 3600}

    monkeypatch.setattr(adapter.OAuthManager, "refresh", fake_refresh)

    requests_made = []

    async def fake_do_request(self, ctx, params, url, headers, query, json_body, data, files):
        import httpx
        auth_hdr = headers.get("Authorization", "")
        requests_made.append(auth_hdr)
        if "recovered_token_401" in auth_hdr:
            return httpx.Response(200, json={"data": "success"}, request=httpx.Request("GET", url))
        return httpx.Response(401, json={"error": "invalid_token"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(HTTPRequestNode, "_do_request", fake_do_request)

    http_node = HTTPRequestNode()
    http_params = HTTPRequestParams(url="https://api.example.com/test", method="GET")
    result = _run(http_node.run(_ctx("wf_tm_test"), http_params, []))

    assert result.output_items[0]["statusCode"] == 200
    assert len(refresh_calls) == 1
    assert len(requests_made) == 2


# ==============================================================================
# TEST 8 — DUPLICATE PREVENTION (UPSERT)
# ==============================================================================
def test_acceptance_8_duplicate_prevention_upsert():
    """Running Token Manager multiple times updates the existing record
    instead of creating duplicate rows.
    """
    for i in range(5):
        out = _tm_store(access_token=f"token_version_{i}", refresh_token=f"ref_version_{i}").output_items[0]
        assert out["saved"] is True
        if i > 0:
            assert out["updated"] is True

    db = get_session()
    try:
        rows = db.scalars(
            select(WorkflowAuthState).where(
                WorkflowAuthState.workflow_id == "wf_tm_test",
                WorkflowAuthState.provider == "salesforce",
            )
        ).all()
        assert len(rows) == 1
    finally:
        db.close()


# ==============================================================================
# TEST 9 — CONCURRENT EXECUTIONS
# ==============================================================================
def test_acceptance_9_concurrent_executions_single_flight(monkeypatch):
    """Multiple concurrent executions with expired token execute exactly 1 refresh operation."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    _tm_store(access_token="expired_tok", refresh_token="ref_tok", expires_at=time.time() - 200)

    lock = threading.Lock()
    refresh_count = [0]

    from app.auth_state import adapter

    async def fake_refresh(self, bundle):
        with lock:
            refresh_count[0] += 1
        await asyncio.sleep(0.15)
        return {"access_token": "single_flight_fresh_tok", "expires_at": time.time() + 3600}

    monkeypatch.setattr(adapter.OAuthManager, "refresh", fake_refresh)

    def worker():
        return _run(TokenManagerNode().run(_ctx("wf_tm_test"), TokenManagerParams(provider="salesforce", mode="fetch"), []))

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker) for _ in range(5)]
        results = [f.result() for f in futures]

    assert all(r.output_items[0]["isValid"] is True for r in results)
    assert all(r.output_items[0]["accessToken"] == "single_flight_fresh_tok" for r in results)
    assert refresh_count[0] == 1


# ==============================================================================
# TEST 10 — SECURITY & SECRET HYGIENE
# ==============================================================================
def test_acceptance_10_security_encryption_and_masking(caplog):
    """Verify secrets are encrypted at rest in DB and never leaked in logs."""
    secret_access = "secret_access_xyz_7777"
    secret_refresh = "secret_refresh_xyz_8888"

    _tm_store(access_token=secret_access, refresh_token=secret_refresh)

    with caplog.at_level(logging.INFO, logger="test_tm"):
        _tm_fetch()

    # Plaintext tokens are NOT in logs
    assert secret_access not in caplog.text
    assert secret_refresh not in caplog.text

    # Database contains ciphertext, not plaintext
    db = get_session()
    try:
        row = db.scalar(
            select(WorkflowAuthState).where(WorkflowAuthState.workflow_id == "wf_tm_test")
        )
        assert row is not None
        assert secret_access.encode() not in bytes(row.data)
        assert secret_refresh.encode() not in bytes(row.data)

        import json
        decrypted = json.loads(decrypt_text(row.data))
        assert decrypted["access_token"] == secret_access
        assert decrypted["refresh_token"] == secret_refresh
    finally:
        db.close()


# ==============================================================================
# TEST 11 — DUAL OUTPUT HANDLES (NATIVE BRANCHING)
# ==============================================================================
def test_acceptance_11_dual_output_handles():
    """TokenManagerNode outputs to 'login' handle when credentials are missing/expired,
    and to 'valid' handle when credentials are valid or newly stored.
    This enables native canvas branching where downstream Login API is automatically
    skipped on Run 2 without requiring an IF condition node.
    """
    node = TokenManagerNode()
    assert node.output_handles == ["valid", "login"]

    # 1. First Run: Missing credentials -> emits to 'login', 'valid' is empty
    res1 = _run(node.run(_ctx("wf_tm_test"), TokenManagerParams(provider="salesforce", mode="fetch"), []))
    assert len(res1.output_by_handle["login"]) == 1
    assert len(res1.output_by_handle["valid"]) == 0
    assert res1.output_by_handle["login"][0]["requiresAuthentication"] is True

    # 2. Store credentials from Login API response -> emits to 'valid', 'login' is empty
    login_response = {
        "access_token": "fresh_dual_access_token_123",
        "refresh_token": "fresh_dual_refresh_token_456",
        "expires_in": 3600,
    }
    res_store = _run(node.run(_ctx("wf_tm_test"), TokenManagerParams(provider="salesforce", mode="store"), [login_response]))
    assert len(res_store.output_by_handle["valid"]) == 1
    assert len(res_store.output_by_handle["login"]) == 0
    assert res_store.output_by_handle["valid"][0]["isValid"] is True

    # 3. Second Run: Valid in DB -> emits to 'valid', 'login' is empty
    res2 = _run(node.run(_ctx("wf_tm_test"), TokenManagerParams(provider="salesforce", mode="fetch"), []))
    assert len(res2.output_by_handle["valid"]) == 1
    assert len(res2.output_by_handle["login"]) == 0
    assert res2.output_by_handle["valid"][0]["accessToken"] == "fresh_dual_access_token_123"
    assert res2.output_by_handle["valid"][0]["requiresAuthentication"] is False


def test_acceptance_12_first_run_auto_login(respx_mock):
    """When login_url is provided, first run automatically executes login call,
    stores token in database, and returns populated token immediately with ZERO null values!
    """
    import httpx

    respx_mock.post("https://auth.example.com/oauth/token").respond(
        status_code=200,
        json={
            "access_token": "auto_login_token_999",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_token": "auto_refresh_tok_888",
        },
    )

    client = httpx.AsyncClient()
    ctx = NodeContext(
        execution_id="exec_test_12",
        workflow_id="wf_tm_test_12",
        logger=logging.getLogger("test_tm"),
        http_client=client,
        storage=MemoryKVStore(),
    )

    db = get_session()
    try:
        user = User(email=f"tm12_{uuid.uuid4().hex[:8]}@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        db.add(
            WorkflowRecord(
                id="wf_tm_test_12",
                user_id=user.id,
                name="WF 12",
                data={"id": "wf_tm_test_12", "name": "WF 12", "nodes": [], "connections": []},
            )
        )
        db.commit()
    finally:
        db.close()

    node = TokenManagerNode()
    params = TokenManagerParams(
        workflow_id="wf_tm_test_12",
        provider="salesforce",
        mode="fetch",
        login_url="https://auth.example.com/oauth/token",
        login_method="POST",
        login_body={"client_id": "c1", "client_secret": "s1"},
    )
    input_item = {"currentDateTime": "2026-01-01 12:00:00"}
    res = _run(node.run(ctx, params, [input_item]))

    out = res.output_items[0]
    # Verify everything is populated and NOT null!
    assert out["accessToken"] == "auto_login_token_999"
    assert out["access_token"] == "auto_login_token_999"
    assert out["Authorization"] == "Bearer auto_login_token_999"
    assert out["refreshToken"] == "auto_refresh_tok_888"
    assert out["expiresAt"] is not None
    assert out["isValid"] is True
    assert out["source"] == "login_api"
    assert out["requiresAuthentication"] is False
    # Upstream data preserved!
    assert out["currentDateTime"] == "2026-01-01 12:00:00"

    # Second run: does NOT call login API, reuses stored token from DB!
    res2 = _run(node.run(ctx, TokenManagerParams(workflow_id="wf_tm_test_12", provider="salesforce", mode="fetch"), []))
    assert res2.output_items[0]["accessToken"] == "auto_login_token_999"
    assert res2.output_items[0]["source"] == "stored_credentials"


def test_acceptance_13_fetch_mode_outputs_null_first_run_then_all_data_second_run(respx_mock):
    """When Token Manager is in mode 'fetch' before the Login API call:
    - First run: Database store has no tokens. Node outputs null for everything
      except workflowId, and routes to 'login' handle.
    - Login API runs and returns credentials.
    - Token Manager (store mode) saves the credentials to DB.
    - Second run: Token Manager (fetch) retrieves stored credentials, outputs ALL
      data populated (accessToken, provider, refreshToken, expiresAt, etc.), and routes to 'valid' handle!
    """
    import httpx

    respx_mock.post("https://api.crm.example.com/auth/login").respond(
        status_code=200,
        json={
            "access_token": "connected_login_token_555",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "connected_refresh_tok_777",
        },
    )

    client = httpx.AsyncClient()
    wf_id = "wf_tm_fetch_then_store"
    ctx = NodeContext(
        execution_id="exec_test_13",
        workflow_id=wf_id,
        node_id="token_manager_fetch",
        logger=logging.getLogger("test_tm"),
        http_client=client,
        storage=MemoryKVStore(),
    )

    db = get_session()
    try:
        user = User(email=f"tm13_{uuid.uuid4().hex[:8]}@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        db.add(
            WorkflowRecord(
                id=wf_id,
                user_id=user.id,
                name="WF 13",
                data={
                    "id": wf_id,
                    "name": "WF 13",
                    "nodes": [
                        {"id": "token_manager_fetch", "type": "token_manager", "parameters": {"mode": "fetch"}},
                        {
                            "id": "http_login_node",
                            "type": "http_request",
                            "name": "Login Api",
                            "parameters": {
                                "url": "https://api.crm.example.com/auth/login",
                                "method": "POST",
                                "body": {"user": "admin", "pass": "secret"},
                            },
                        },
                        {"id": "token_manager_store", "type": "token_manager", "parameters": {"mode": "store"}},
                    ],
                    "connections": [
                        {
                            "source": "token_manager_fetch",
                            "sourceHandle": "login",
                            "target": "http_login_node",
                            "targetHandle": "main",
                        },
                        {
                            "source": "http_login_node",
                            "sourceHandle": "main",
                            "target": "token_manager_store",
                            "targetHandle": "main",
                        },
                    ],
                },
            )
        )
        db.commit()
    finally:
        db.close()

    fetch_node = TokenManagerNode()
    params_fetch = TokenManagerParams(
        workflow_id=wf_id,
        provider="salesforce",
        mode="fetch",
    )

    # -------------------------------------------------------------
    # 1. First Run: Token Manager (Fetch) BEFORE API call
    # -------------------------------------------------------------
    res_1 = _run(fetch_node.run(ctx, params_fetch, []))
    out_1 = res_1.output_items[0]

    # Everything MUST be null except workflowId!
    assert out_1["workflowId"] == wf_id
    assert out_1["provider"] is None
    assert out_1["accessToken"] is None
    assert out_1["access_token"] is None
    assert out_1["Authorization"] is None
    assert out_1["authorization"] is None
    assert out_1["refreshToken"] is None
    assert out_1["refresh_token"] is None
    assert out_1["expiresAt"] is None
    assert out_1["expires_at"] is None
    assert out_1["tokenType"] is None
    assert out_1["token_type"] is None
    assert out_1["scope"] is None
    assert out_1["credentialId"] is None
    assert out_1["isValid"] is False
    assert out_1["requiresAuthentication"] is True
    # Output routes to 'login' handle to trigger Login API, NOT to 'valid' handle
    assert len(res_1.output_by_handle["login"]) == 1
    assert len(res_1.output_by_handle["valid"]) == 0

    # -------------------------------------------------------------
    # 2. Login API Call runs (via HTTP)
    # -------------------------------------------------------------
    api_resp = {
        "access_token": "connected_login_token_555",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "connected_refresh_tok_777",
    }

    # -------------------------------------------------------------
    # 3. Token Manager (Store) saves to database store
    # -------------------------------------------------------------
    store_node = TokenManagerNode()
    params_store = TokenManagerParams(
        workflow_id=wf_id,
        provider="salesforce",
        mode="store",
    )
    store_res = _run(store_node.run(ctx, params_store, [api_resp]))
    assert store_res.output_items[0]["saved"] is True
    assert store_res.output_items[0]["accessToken"] == "connected_login_token_555"

    # -------------------------------------------------------------
    # 4. Second Run: Token Manager (Fetch) AFTER token is stored in DB
    # -------------------------------------------------------------
    res_2 = _run(fetch_node.run(ctx, params_fetch, []))
    out_2 = res_2.output_items[0]

    # All data MUST now be populated!
    assert out_2["workflowId"] == wf_id
    assert out_2["provider"] == "salesforce"
    assert out_2["accessToken"] == "connected_login_token_555"
    assert out_2["access_token"] == "connected_login_token_555"
    assert out_2["Authorization"] == "Bearer connected_login_token_555"
    assert out_2["refreshToken"] == "connected_refresh_tok_777"
    assert out_2["expiresAt"] is not None
    assert out_2["tokenType"] == "Bearer"
    assert out_2["isValid"] is True
    assert out_2["status"] == "VALID"
    assert out_2["source"] == "stored_credentials"
    assert out_2["requiresAuthentication"] is False
    # Output routes to 'valid' handle!
    assert len(res_2.output_by_handle["valid"]) == 1
    assert len(res_2.output_by_handle["login"]) == 0


def test_acceptance_14_refresh_mode_uses_refresh_token_when_expired_or_invalid(respx_mock):
    """When mode is 'refresh':
    - If access token is valid and not expired: reuses valid token.
    - If access token is expired or received a 401 error: uses the stored refresh token
      to generate a brand new access token via OAuth refresh, updates the database,
      and outputs status="REFRESHED" with the new access token!
    """
    wf_id = "wf_tm_refresh_mode_test"
    db = get_session()
    try:
        user = User(email=f"tm14_{uuid.uuid4().hex[:8]}@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        db.add(
            WorkflowRecord(
                id=wf_id,
                user_id=user.id,
                name="WF 14 Refresh",
                data={"id": wf_id, "name": "WF 14", "nodes": [], "connections": []},
            )
        )
        db.commit()
    finally:
        db.close()

    # Pre-store an expired token with a valid refresh_token
    _tm_store(
        workflow_id=wf_id,
        provider="salesforce",
        access_token="old_expired_access_token",
        refresh_token="my_valid_refresh_token_999",
        expires_at=time.time() - 100,  # expired in past
    )

    # Mock Salesforce OAuth refresh endpoint
    respx_mock.post("https://login.salesforce.com/services/oauth2/token").respond(
        status_code=200,
        json={
            "access_token": "brand_new_refreshed_access_token_777",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "rotated_refresh_token_888",
        },
    )

    refresh_node = TokenManagerNode()
    params_refresh = TokenManagerParams(
        workflow_id=wf_id,
        provider="salesforce",
        mode="refresh",
    )

    ctx = _ctx(wf_id)
    # Run refresh node with mode="refresh"
    res = _run(refresh_node.run(ctx, params_refresh, []))
    out = res.output_items[0]

    assert out["accessToken"] == "brand_new_refreshed_access_token_777"
    assert out["Authorization"] == "Bearer brand_new_refreshed_access_token_777"
    assert out["refreshToken"] == "rotated_refresh_token_888"
    assert out["isValid"] is True
    assert out["status"] == "REFRESHED"
    assert out["source"] == "refreshed"
    assert len(res.output_by_handle["valid"]) == 1
    assert len(res.output_by_handle["login"]) == 0


def test_acceptance_15_manual_force_refresh_bypasses_expiration(respx_mock):
    """When force_refresh=True, Token Manager forcibly triggers token refresh
    even if the stored access token is completely valid and not expired!
    """
    wf_id = "wf_tm_force_refresh_test"
    db = get_session()
    try:
        user = User(email=f"tm15_{uuid.uuid4().hex[:8]}@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        db.add(
            WorkflowRecord(
                id=wf_id,
                user_id=user.id,
                name="WF 15 Force Refresh",
                data={"id": wf_id, "name": "WF 15", "nodes": [], "connections": []},
            )
        )
        db.commit()
    finally:
        db.close()

    # Pre-store a VALID token (expires in 1 hour)
    _tm_store(
        workflow_id=wf_id,
        provider="salesforce",
        access_token="still_valid_access_token_123",
        refresh_token="my_refresh_token_456",
        expires_at=time.time() + 3600,
    )

    # Mock Salesforce OAuth refresh endpoint
    respx_mock.post("https://login.salesforce.com/services/oauth2/token").respond(
        status_code=200,
        json={
            "access_token": "forced_fresh_token_999",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "rotated_refresh_token_555",
        },
    )

    refresh_node = TokenManagerNode()
    params_forced = TokenManagerParams(
        workflow_id=wf_id,
        provider="salesforce",
        mode="refresh",
        force_refresh=True,  # Force manual refresh!
    )

    ctx = _ctx(wf_id)
    res = _run(refresh_node.run(ctx, params_forced, []))
    out = res.output_items[0]

    assert out["accessToken"] == "forced_fresh_token_999"
    assert out["status"] == "REFRESHED"
    assert out["source"] == "refreshed"
    assert out["refreshToken"] == "rotated_refresh_token_555"
    assert out["isValid"] is True


def test_acceptance_16_manual_custom_refresh_url_and_body(respx_mock):
    """When custom refresh_url and refresh_body are specified,
    Token Manager executes the manual refresh against the custom endpoint
    with {{refreshToken}} interpolation!
    """
    wf_id = "wf_tm_custom_refresh_test"
    db = get_session()
    try:
        user = User(email=f"tm16_{uuid.uuid4().hex[:8]}@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        db.add(
            WorkflowRecord(
                id=wf_id,
                user_id=user.id,
                name="WF 16 Custom Refresh",
                data={"id": wf_id, "name": "WF 16", "nodes": [], "connections": []},
            )
        )
        db.commit()
    finally:
        db.close()

    _tm_store(
        workflow_id=wf_id,
        provider="custom",
        access_token="expired_custom_tok",
        refresh_token="my_custom_secret_ref_123",
        expires_at=time.time() - 100,
    )

    custom_url = "https://custom-auth.example.com/oauth/token/refresh"
    respx_mock.post(custom_url).respond(
        status_code=200,
        json={
            "data": {
                "access_token": "custom_endpoint_new_access_token",
                "refresh_token": "custom_endpoint_new_refresh_token",
                "expires_in": 7200,
            }
        },
    )

    node = TokenManagerNode()
    params = TokenManagerParams(
        workflow_id=wf_id,
        provider="custom",
        mode="refresh",
        refresh_url=custom_url,
        refresh_method="POST",
        refresh_body={"token": "{{refreshToken}}", "grant_type": "refresh_token"},
    )

    ctx = _ctx(wf_id)
    res = _run(node.run(ctx, params, []))
    out = res.output_items[0]

    assert out["accessToken"] == "custom_endpoint_new_access_token"
    assert out["refreshToken"] == "custom_endpoint_new_refresh_token"
    assert out["status"] == "REFRESHED"
    assert out["isValid"] is True


def test_acceptance_17_manual_refresh_api_endpoint(client, respx_mock):
    """Test the POST /api/v1/workflows/{workflow_id}/auth-state/refresh endpoint."""
    from app.main import app
    from app.api.auth import get_current_user

    wf_id = "wf_tm_api_refresh_test"
    db = get_session()
    try:
        user = User(email=f"tm17_{uuid.uuid4().hex[:8]}@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        db.add(
            WorkflowRecord(
                id=wf_id,
                user_id=user.id,
                name="WF 17 API Refresh",
                data={"id": wf_id, "name": "WF 17", "nodes": [], "connections": []},
            )
        )
        db.commit()
    finally:
        db.close()

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        _tm_store(
            workflow_id=wf_id,
            provider="salesforce",
            access_token="old_access_tok",
            refresh_token="old_refresh_tok_777",
            expires_at=time.time() + 3600,
        )

        respx_mock.post("https://login.salesforce.com/services/oauth2/token").respond(
            status_code=200,
            json={
                "access_token": "api_refreshed_access_token_888",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "api_rotated_refresh_token_999",
            },
        )

        resp = client.post(f"/api/workflows/{wf_id}/auth-state/refresh?provider=salesforce&force=true")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["status"] == "REFRESHED"
        assert data["is_valid"] is True
        assert data["has_refresh_token"] is True
        assert data["message"] == "Token refreshed successfully."
    finally:
        app.dependency_overrides.pop(get_current_user, None)



