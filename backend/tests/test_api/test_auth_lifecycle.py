"""Auth fetch/store lifecycle tests (auth feature).

Covers the acceptance cases: first-run MISSING, reuse without login,
expired auto-refresh (rotation preserved), refresh-failure reauth
shape, no-refresh-token path, no unnecessary auth work, concurrent
single-refresh, and secret hygiene. No network (refresh mocked).
"""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from app.engine.node_base import MemoryKVStore, NodeContext


def _ctx(workflow_id="wf_auth"):
    return NodeContext(
        execution_id="e", workflow_id=workflow_id, logger=logging.getLogger("t"),
        http_client=None, storage=MemoryKVStore(),
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _workflow_row():
    """Parent workflow (+owner) for the FK on workflow_auth_state."""
    import uuid

    from app.db import get_session
    from app.models.user import User
    from app.models.workflow import WorkflowRecord

    db = get_session()
    try:
        user = User(email=f"auth_{uuid.uuid4().hex[:8]}@test.com", password_hash="x")
        db.add(user)
        db.flush()
        db.add(WorkflowRecord(
            id="wf_auth", user_id=user.id, name="Auth",
            data={"id": "wf_auth", "name": "Auth", "nodes": [], "connections": [], "settings": {}},
        ))
        db.commit()
        yield
    finally:
        db.close()


def _store(provider="custom", access_token="tok-1", refresh_token="ref-1", **kw):
    from app.nodes.auth_store import AuthStoreNode, AuthStoreParams

    params = {
        "provider": provider, "access_token": access_token,
        "refresh_token": refresh_token, "token_url": "https://auth.example/token",
        "client_id": "cid", "client_secret": "csecret",
        "expires_at": time.time() + 3600,
    }
    params.update(kw)
    return _run(AuthStoreNode().run(_ctx(), AuthStoreParams(**params), []))


def _fetch(provider="custom", **kw):
    from app.nodes.auth_fetch import AuthFetchNode, AuthFetchParams

    params = {"provider": provider}
    params.update(kw)
    return _run(AuthFetchNode().run(_ctx(), AuthFetchParams(**params), []))


def _patch_refresh(monkeypatch, calls, result=None, error=None):
    from app.auth_state import adapter

    async def fake(self, bundle):
        calls.append(dict(bundle))
        if error is not None:
            raise error
        out = {"access_token": "tok-2", "expires_at": time.time() + 3600}
        if result:
            out.update(result)
        return out

    monkeypatch.setattr(adapter.OAuthManager, "refresh", fake)


# Test 1 — first execution: MISSING, authentication required.
def test_first_run_missing_requires_authentication():
    out = _fetch().output_items[0]
    assert out["status"] == "MISSING"
    assert out["requiresAuthentication"] is True
    assert out["accessToken"] is None and out["refreshToken"] is None
    assert out["isValid"] is False
    assert out["workflowId"] == "wf_auth"


# Test 2 — second execution reuses stored credentials (no login path).
def test_second_run_reuses_without_login():
    saved = _store().output_items[0]
    assert saved["saved"] is True
    out = _fetch().output_items[0]
    assert out["status"] == "VALID" and out["isValid"] is True
    assert out["accessToken"] == "tok-1" and out["refreshToken"] == "ref-1"
    assert out["requiresAuthentication"] is False


# Test 3 — expired access token auto-refreshes; rotation preserved.
def test_expired_refreshes_and_preserves_rotation(monkeypatch):
    _store(expires_at=time.time() - 100)
    calls: list = []
    _patch_refresh(monkeypatch, calls)  # no refresh_token in result
    out = _fetch().output_items[0]
    assert out["status"] == "REFRESHED" and out["isValid"] is True
    assert out["accessToken"] == "tok-2"
    assert out["refreshToken"] == "ref-1"  # preserved, not rotated
    assert len(calls) == 1
    # Persisted: next fetch is VALID without another refresh.
    out2 = _fetch().output_items[0]
    assert out2["status"] == "VALID" and out2["accessToken"] == "tok-2"
    assert len(calls) == 1


# Test 4 — refresh failure yields reauth shape (no throw).
def test_refresh_failure_goes_to_reauth(monkeypatch):
    _store(expires_at=time.time() - 100)
    _patch_refresh(monkeypatch, [], error=ValueError("Token refresh failed 400"))
    out = _fetch().output_items[0]
    assert out["status"] == "REAUTH_REQUIRED"
    assert out["requiresAuthentication"] is True
    assert out["isValid"] is False


# Test 5 — no refresh token goes straight to reauth (no refresh call).
def test_no_refresh_token_skips_refresh(monkeypatch):
    _store(refresh_token="", expires_at=time.time() - 100)
    calls: list = []
    _patch_refresh(monkeypatch, calls)
    out = _fetch().output_items[0]
    assert out["status"] == "REAUTH_REQUIRED"
    assert calls == []


# Test 6 — valid token performs no auth work at all.
def test_valid_token_skips_all_auth_work(monkeypatch):
    _store()
    calls: list = []
    _patch_refresh(monkeypatch, calls)
    out = _fetch().output_items[0]
    assert out["status"] == "VALID"
    assert calls == []


# Test 7 — concurrent expired fetches refresh exactly once.
def test_concurrent_refresh_single_flight(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    _store(expires_at=time.time() - 100)
    calls: list = []
    lock = threading.Lock()
    real_calls = calls

    from app.auth_state import adapter

    async def fake(self, bundle):
        with lock:
            real_calls.append(1)
        await asyncio.sleep(0.2)
        return {"access_token": "tok-N", "expires_at": time.time() + 3600}

    monkeypatch.setattr(adapter.OAuthManager, "refresh", fake)

    def one():
        # Threads model separate workers (production never shares one
        # event loop between executions; sync psycopg2 would deadlock a
        # shared loop under row-lock wait).
        from app.nodes.auth_fetch import AuthFetchNode, AuthFetchParams

        return _run(AuthFetchNode().run(_ctx(), AuthFetchParams(provider="custom"), []))

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: one(), range(3)))
    assert all(r.output_items[0]["isValid"] for r in results)
    assert len(real_calls) == 1


# Test 8 — secret hygiene: logs/errors/DB carry no plaintext tokens.
def test_secrets_never_leak(caplog):
    from app.db import get_session
    from app.models.workflow_auth import WorkflowAuthState
    from sqlalchemy import select

    _store(access_token="tok-secret-xyz", refresh_token="ref-secret-xyz")
    with caplog.at_level(logging.INFO, logger="t"):
        _fetch()
    assert "tok-secret-xyz" not in caplog.text
    assert "ref-secret-xyz" not in caplog.text

    db = get_session()
    try:
        row = db.scalar(
            select(WorkflowAuthState).where(WorkflowAuthState.workflow_id == "wf_auth")
        )
        assert row is not None
        assert b"tok-secret-xyz" not in bytes(row.data)
        assert b"ref-secret-xyz" not in bytes(row.data)
    finally:
        db.close()
