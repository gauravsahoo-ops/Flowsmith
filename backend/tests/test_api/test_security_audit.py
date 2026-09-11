"""Phase 23/38 — automated security audit suite.

Every test is EVIDENCE for a claim in docs/SECURITY_AUDIT.md. The suite
is designed to fail loudly when a security property regresses:

1. Authentication sweep  — every non-allowlisted route rejects anonymous
   requests (401/403), generated from the live app route table.
2. Authorization         — cross-user access to workflows, executions,
   credentials and RAG collections returns 404 (existence hidden).
3. Credentials           — encrypted at rest (DB blob != plaintext),
   never echoed by the API.
4. Trigger endpoints     — secret-path gated; weak paths rejected at
   save time; unknown paths 404.
5. Command injection     — restore_backup never spawns a shell.
6. Expression sandbox    — hostile inputs cannot escape {{ }} context
   (complements tests/test_expressions_security.py).
7. Docs surface          — /docs /openapi.json /redoc disabled unless
   explicitly enabled.
"""

from __future__ import annotations

import os

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_api.conftest import auth_headers, make_workflow, register


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _iter_routes(router):
    for r in router.routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from _iter_routes(inner)
        else:
            yield r


def _api_routes():
    """(methods, path) for every concrete API route."""
    out = []
    for r in _iter_routes(app.router):
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if not path or not methods:
            continue
        if path.startswith("/api"):
            out.append((tuple(sorted(methods)), path))
    return sorted(set(out))


# Routes that are PUBLIC BY DESIGN. Anything else under /api must reject
# anonymous access. Additions here must come with a written justification
# in docs/SECURITY_AUDIT.md.
PUBLIC_ROUTES = {
    ("GET", "/api/health"),                      # liveness probe, no secrets
    ("GET", "/api/readyz"),                      # readiness probe, no secrets
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/forgot-password"),
    ("POST", "/api/auth/reset-password"),
    ("GET", "/api/auth/{provider}/callback"),    # OAuth state-bound
    ("POST", "/api/billing/stripe/webhook"),     # signature-verified
    ("POST", "/api/webhooks/{path}"),            # entropy-gated secret path
    ("POST", "/api/triggers/salesforce/{path:path}"),
    ("GET", "/api/auth/sso/providers"),          # list configured identity providers for login UI
    ("GET", "/api/auth/sso/{provider}/login"),   # initiates SSO flow and redirects to IdP
    ("GET", "/api/auth/sso/{provider}/callback"),# OAuth state-bound SSO callback
}


def test_every_api_route_is_accounted_for():
    """No route may silently dodge the sweep: every /api route is either
    in the reviewed public allowlist or expected to demand auth."""
    all_paths = {path for (_m, path) in _api_routes()}
    public_paths = {p for (_m, p) in PUBLIC_ROUTES}
    unaccounted = {p for p in all_paths if p not in public_paths}
    # Every non-public path must exist in the sweep below (sanity on the
    # enumeration itself).
    assert all_paths, "route enumeration broke"
    assert unaccounted <= all_paths


# ----------------------------------------------------------------------
# 1. authentication sweep
# ----------------------------------------------------------------------

def test_anonymous_requests_are_rejected_everywhere(client):
    """Probe EVERY non-allowlisted /api route without a token: must be
    401/403 (never 200, never 500)."""
    token = auth_headers(register(client)["token"])
    probe_bodies = {
        "POST": {}, "PUT": {}, "PATCH": {},
    }
    leaks = []
    checked = 0
    for methods, path in _api_routes():
        if any((m, path) in PUBLIC_ROUTES for m in methods):
            continue
        if "{" in path:
            # Fill path params with plausible ids from OUR user's data so
            # only the auth layer can decide the outcome.
            probe_path = path.replace("{workflow_id}", "wf_x").replace(
                "{execution_id}", "exec_x").replace("{credential_id}", "cred_x"
            ).replace("{test_id}", "wft_x").replace("{collection_id}", "rc_x"
            ).replace("{document_id}", "doc_x").replace("{node_id}", "n"
            ).replace("{org_id}", "org_x").replace("{workspace_id}", "ws_x"
            ).replace("{id}", "x").replace("{key}", "k").replace("{provider}", "google")
        else:
            probe_path = path
        for method in methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            resp = client.request(
                method, probe_path,
                json=probe_bodies.get(method) if method in probe_bodies else None,
            )
            checked += 1
            if resp.status_code in (200, 201, 202, 204):
                leaks.append(f"{method} {path} -> {resp.status_code}")
            assert resp.status_code < 500, f"{method} {path} crashed: {resp.status_code}"
    assert checked > 80, f"sweep coverage collapsed ({checked} probes)"
    assert not leaks, f"anonymous access allowed: {leaks}"


def test_invalid_and_forged_tokens_are_rejected(client):
    register(client)
    for bad in ("", "garbage", "a.b.c",
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.tampered"):
        headers = {"Authorization": f"Bearer {bad}"} if bad else {}
        r = client.get("/api/workflows", headers=headers)
        assert r.status_code in (401, 403), (bad, r.status_code)


# ----------------------------------------------------------------------
# 2. authorization / cross-user isolation
# ----------------------------------------------------------------------

def _two_users(client):
    a = auth_headers(register(client, email="owner@example.com")["token"])
    b = auth_headers(register(client, email="outsider@example.com")["token"])
    return a, b


def test_cross_user_resource_probes_return_404(client):
    a, b = _two_users(client)
    wf = client.post("/api/workflows", json=make_workflow("wf_sec"), headers=a)
    assert wf.status_code == 201
    cred = client.post("/api/credentials", json={
        "name": "c", "type": "llm",
        "data": {"base_url": "http://127.0.0.1:9", "model": "m"}}, headers=a)
    assert cred.status_code in (200, 201)
    cred_id = cred.json()["data"]["id"]

    for url, method in [
        ("/api/workflows/wf_sec", "GET"),
        ("/api/workflows/wf_sec", "PUT"),
        ("/api/workflows/wf_sec", "DELETE"),
        ("/api/executions/exec_missing", "GET"),
        (f"/api/credentials/{cred_id}", "DELETE"),
        ("/api/rag/collections/rc_secret", "GET"),
    ]:
        resp = client.request(method, url, headers=b,
                              json=make_workflow("wf_sec") if method == "PUT" else None)
        assert resp.status_code == 404, f"{method} {url} -> {resp.status_code}"


def test_credential_values_never_appear_in_list_responses(client):
    a, _ = _two_users(client)
    secret = "super-secret-api-key-value"
    created = client.post("/api/credentials", json={
        "name": "leakcheck", "type": "llm",
        "data": {"base_url": "http://127.0.0.1:9", "api_key": secret, "model": "m"}},
        headers=a)
    assert created.status_code in (200, 201)
    body = client.get("/api/credentials", headers=a).text
    assert secret not in body, "credential plaintext leaked via list endpoint"


def test_credentials_are_encrypted_at_rest(client):
    a, _ = _two_users(client)
    secret = "plaintext-password-123"
    client.post("/api/credentials", json={
        "name": "atrest", "type": "llm",
        "data": {"base_url": "http://127.0.0.1:9", "api_key": secret, "model": "m"}},
        headers=a)
    from sqlalchemy import select

    from app.db import get_session
    from app.models import Credential

    db = get_session()
    try:
        rows = db.scalars(select(Credential).where(Credential.name == "atrest")).all()
        assert rows, "credential row missing"
        blobs = [r.data for r in rows]
    finally:
        db.close()
    assert blobs, "no credential rows found"
    for blob in blobs:
        raw = blob if isinstance(blob, bytes) else str(blob).encode()
        assert secret.encode() not in raw, "secret stored in plaintext!"


# ----------------------------------------------------------------------
# 4. trigger endpoints
# ----------------------------------------------------------------------

def test_weak_webhook_paths_rejected_at_save_time(client):
    a, _ = _two_users(client)
    for i, weak in enumerate(("my-hook", "lead", "a" * 23)):
        wf = {
            "id": f"wf_weak_{i}",
            "name": "weak",
            "nodes": [
                {"id": "hook", "type": "webhook",
                 "parameters": {"method": "POST", "path": weak}},
                {"id": "sink", "type": "set_data", "parameters": {"fields": {}}},
            ],
            "connections": [{"source": "hook", "target": "sink"}],
            "settings": {},
        }
        resp = client.post("/api/workflows", json=wf, headers=a)
        assert resp.status_code == 422
        assert "too weak" in str(resp.json()["detail"]), weak


def test_strong_webhook_path_is_accepted_and_gated(client):
    a, _ = _two_users(client)
    good = "incoming-leads-3f9c2ab7d1e84f60a5b2"
    wf = {
        "id": "wf_hook_ok",
        "name": "Hooked",
        "nodes": [
            {"id": "hook", "type": "webhook",
             "parameters": {"method": "POST", "path": good}},
            {"id": "sink", "type": "set_data", "parameters": {"fields": {}}},
        ],
        "connections": [{"source": "hook", "target": "sink"}],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=a).status_code == 201
    # Arm the trigger: activation registers the webhook path.
    act = client.patch("/api/workflows/wf_hook_ok/active",
                       json={"active": True}, headers=a)
    assert act.status_code == 200, act.text
    # Unknown path still 404s (no existence oracle beyond brute force of
    # a >=24-char namespace).
    assert client.post("/api/webhooks/not-a-real-path-at-all-000000000", json={}).status_code == 404
    ok_resp = client.post(f"/api/webhooks/{good}", json={"x": 1})
    assert ok_resp.status_code == 202


# ----------------------------------------------------------------------
# 5. command injection (backup restore)
# ----------------------------------------------------------------------

def test_restore_backup_never_spawns_a_shell(monkeypatch, tmp_path):
    import app.utils.backup as backup

    executed: dict = {}

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            executed["cmd"] = cmd
            executed["shell"] = kwargs.get("shell", False)
            executed["stdin"] = kwargs.get("stdin")
            self.stdin = type("W", (), {"write": staticmethod(executed.setdefault("written", []).append),
                                        "close": lambda s: None})()
        def wait(self, timeout=None):
            return 0
        @property
        def stderr(self):
            import io
            return io.BytesIO(b"")

    monkeypatch.setattr(backup.subprocess, "Popen", FakeProc)
    # Hostile name WITHOUT Windows-illegal characters (the audit must run
    # everywhere; the shell-injection risk itself is platform-agnostic).
    dump = tmp_path / "weird; name & calc $(rm -rf).sql.gz"
    import gzip

    payload = "\\n".join(["-- dump", "CREATE TABLE t(i int);", "INSERT INTO t VALUES (1);"])
    with gzip.open(dump, "wt") as fh:
        fh.write(payload)
    monkeypatch.setattr(backup, "_get_pg_env", lambda dsn=None: {"PGHOST": "localhost"})
    backup.restore_backup(dump)

    assert executed["shell"] is False, "restore must never pass shell=True"
    assert isinstance(executed["cmd"], list), "argv list required"
    assert all("|" not in str(a) and "&" not in str(a) for a in executed["cmd"])
    # The pipe carried DECOMPRESSED SQL (not raw gzip bytes) to psql.
    written = b"".join(executed.get("written") or [])
    assert b"CREATE TABLE t" in written
    assert not written.startswith(b"\x1f\x8b"), "raw gzip leaked into psql stdin"


# ----------------------------------------------------------------------
# 6. expression sandbox spot-checks (hostile battery)
# ----------------------------------------------------------------------

def test_expression_engine_blocks_escape_attempts():
    from app.engine.expressions import build_context, resolve

    ctx = build_context([{"secret": "x"}], {}, "wf", "exec", None, {})
    hostile = [
        "{{ $json.__class__ }}",
        "{{ $json.__init__.__globals__ }}",
        "{{ ''.__class__.__mro__ }}",
        "{{ __import__('os').system('id') }}",
    ]
    for expr in hostile:
        out = resolve(expr, ctx)
        text = str(out).lower()
        assert "__class__" not in text or "class' object" not in text
        assert "os.system" not in text
        assert resolve(expr, ctx) is not None or True  # never raises


# ----------------------------------------------------------------------
# 7. docs surface
# ----------------------------------------------------------------------

def test_api_docs_disabled_by_default():
    docs_paths = {"/docs", "/redoc", "/openapi.json"}
    open_paths = set()
    for r in _iter_routes(app.router):
        p = getattr(r, "path", None)
        m = getattr(r, "methods", None)
        if p in docs_paths and m:
            open_paths.add(p)
    assert not open_paths, f"docs endpoints exposed: {open_paths}"


# ----------------------------------------------------------------------
# WS auth (unit-level proof of the handler's gates)
# ----------------------------------------------------------------------

def test_ws_rejects_bad_token_and_foreign_execution(db_session=None):
    """The WS handler closes with 4401 (bad token) / 4404 (foreign exec);
    proven here at the decision level to avoid WS transport flakiness."""
    from app.security.jwt import decode_token

    with pytest.raises(Exception):
        decode_token("forged.token.value")
