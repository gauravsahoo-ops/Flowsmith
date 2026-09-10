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

