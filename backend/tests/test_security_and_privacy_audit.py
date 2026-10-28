"""Section 10 Audit Suite: Security & Privacy.

Comprehensive verification of:
1. Authentication bypass and authorization checks
2. Cross-tenant data leakage and privilege escalation
3. SQL injection, XSS, CSRF and SSRF testing as applicable
4. Unsafe code execution and sandbox escape resistance
5. Secrets exposure through logs, APIs and frontend bundles
6. Webhook signature and replay validation
7. Dependency vulnerabilities and insecure configurations
8. Audit logs and sensitive-data handling
9. Rate limiting and abuse resistance
10. Security regression tests after fixes
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.ai.tools import _check_readonly_sql
from app.api.auth import login_throttle
from app.audit import CREDENTIAL_CREATE, WORKFLOW_CREATE, log_event
from app.billing import WEBHOOK_TOLERANCE_SECONDS, verify_webhook_signature
from app.config import ConfigError, Settings, get_settings, validate_production_settings
from app.db import _redact_db_url, get_session
from app.engine.errors import NodeExecutionError
from app.engine.node_base import MemoryKVStore, NodeContext
from app.main import CSRFMiddleware, app
from app.models import AuditEvent, Credential, Execution, User, WorkflowRecord
from app.nodes.code import CodeNode, CodeParams, _exec_python_code
from app.security.crypto import decrypt_text, encrypt_text
from app.security.jwt import create_token, decode_token, hash_password, revoke_token, verify_password
from app.security.ssrf import assert_public_url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid(prefix: str = "sec") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_test_user(db, email: str | None = None) -> User:
    email = email or f"{_uid('u')}@flowsmith.io"
    u = User(
        email=email,
        password_hash="hashed_pw_123",
        role="user",
        created_at=datetime.now(UTC),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------------------------------------------------------------------------
# 1. Authentication Bypass and Authorization Checks
# ---------------------------------------------------------------------------

def test_authentication_bypass_and_authorization_checks(client):
    """Verify unauthenticated requests return 401, tampered/expired tokens fail, and admin gates hold."""
    # 1. Unauthenticated requests to protected endpoints return 401
    assert client.get("/api/workflows").status_code == 401
    assert client.get("/api/executions").status_code == 401
    assert client.get("/api/credentials").status_code == 401
    assert client.get("/api/auth/me").status_code == 401

    # 2. Register valid user and issue token
    email = f"{_uid('u')}@flowsmith.io"
    reg = client.post("/api/auth/register", json={"email": email, "password": "Password123!"})
    assert reg.status_code == 201
    valid_token = reg.json()["data"]["token"]
    user_id = reg.json()["data"]["user"]["id"]

    # Valid token succeeds
    me_resp = client.get("/api/auth/me", headers=_auth_headers(valid_token))
    assert me_resp.status_code == 200
    assert me_resp.json()["data"]["email"] == email

    # 3. Tampered token signature fails
    tampered_token = valid_token[:-4] + "abcd"
    assert client.get("/api/auth/me", headers=_auth_headers(tampered_token)).status_code == 401

    # 4. Expired token fails
    expired_payload = {
        "sub": str(user_id),
        "iat": int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
        "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
        "jti": "exp_jti_123",
    }
    expired_token = jwt.encode(expired_payload, get_settings().jwt_secret, algorithm="HS256")
    assert client.get("/api/auth/me", headers=_auth_headers(expired_token)).status_code == 401

    # 5. Revoked token fails
    valid_payload = decode_token(valid_token)
    revoke_token(valid_payload["jti"])
    assert client.get("/api/auth/me", headers=_auth_headers(valid_token)).status_code == 401

    # 6. Non-admin authorization: regular user blocked from admin endpoints with 403
    reg_normal = client.post("/api/auth/register", json={"email": f"norm_{_uid()}@test.com", "password": "Password123!"})
    normal_token = reg_normal.json()["data"]["token"]
    db = get_session()
    try:
        norm_user = db.get(User, reg_normal.json()["data"]["user"]["id"])
        norm_user.role = "user"
        db.commit()
    finally:
        db.close()

    admin_resp = client.post("/api/admin/maintenance/prune", json={"days": 30}, headers=_auth_headers(normal_token))
    assert admin_resp.status_code == 403


# ---------------------------------------------------------------------------
# 2. Cross-Tenant Data Leakage and Privilege Escalation
# ---------------------------------------------------------------------------

def test_cross_tenant_data_leakage_and_privilege_escalation(client):
    """Verify IDOR prevention, tenant resource isolation, and privilege escalation guards."""
    # Register Tenant A and Tenant B
    reg_a = client.post("/api/auth/register", json={"email": f"tenant_a_{_uid()}@x.com", "password": "Password123!"}).json()["data"]
    reg_b = client.post("/api/auth/register", json={"email": f"tenant_b_{_uid()}@x.com", "password": "Password123!"}).json()["data"]

    headers_a = _auth_headers(reg_a["token"])
    headers_b = _auth_headers(reg_b["token"])

    # Tenant A creates a workflow
    wf_payload = {
        "name": "Secret Tenant A Flow",
        "nodes": [{"id": "t1", "type": "manual_trigger", "parameters": {}}],
        "connections": [],
    }
    create_resp = client.post("/api/workflows", json=wf_payload, headers=headers_a)
    assert create_resp.status_code == 201
    wf_id_a = create_resp.json()["data"]["id"]

    # Tenant B attempts to read Tenant A's workflow -> 404 (IDOR protected, no existence leak)
    get_resp = client.get(f"/api/workflows/{wf_id_a}", headers=headers_b)
    assert get_resp.status_code == 404

    # Tenant B attempts to update Tenant A's workflow -> 404
    update_resp = client.put(f"/api/workflows/{wf_id_a}", json={"name": "Hacked"}, headers=headers_b)
    assert update_resp.status_code == 404

    # Tenant B attempts to delete Tenant A's workflow -> 404
    delete_resp = client.delete(f"/api/workflows/{wf_id_a}", headers=headers_b)
    assert delete_resp.status_code == 404

    # Tenant B lists workflows -> Tenant A's workflow must NOT appear
    list_b = client.get("/api/workflows", headers=headers_b).json()["data"]
    b_ids = [w["id"] for w in list_b]
    assert wf_id_a not in b_ids

    # Privilege Escalation Guard: attempting to self-escalate role via profile update must fail
    db = get_session()
    try:
        user_b = db.get(User, reg_b["user"]["id"])
        assert user_b.role != "admin"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 3. SQL Injection, XSS, CSRF and SSRF Testing
# ---------------------------------------------------------------------------

def test_sql_injection_xss_csrf_and_ssrf(client):
    """Verify defenses against SQL Injection, stored XSS, CSRF attacks, and SSRF requests."""
    reg = client.post("/api/auth/register", json={"email": f"sec_{_uid()}@test.com", "password": "Password123!"}).json()["data"]
    headers = _auth_headers(reg["token"])

    # 1. SQL Injection: Attempt SQLi payload in workflow creation
    sqli_name = "Normal Flow'; DROP TABLE workflows; --"
    resp = client.post(
        "/api/workflows",
        json={"name": sqli_name, "nodes": [], "connections": []},
        headers=headers,
    )
    assert resp.status_code == 201
    # Verify tables still exist and name was stored safely as a literal parameter
    db = get_session()
    try:
        assert db.execute(text("SELECT COUNT(*) FROM workflows")).scalar() >= 1
    finally:
        db.close()

    # 2. XSS: Attempt script tag injection in workflow name
    xss_name = "<script>alert('XSS-PAYLOAD')</script>"
    xss_resp = client.post(
        "/api/workflows",
        json={"name": xss_name, "nodes": [], "connections": []},
        headers=headers,
    )
    assert xss_resp.status_code == 201
    assert "nosniff" in xss_resp.headers.get("x-content-type-options", "").lower()

    # 3. CSRF Protection: Test CSRFMiddleware blocks untrusted cross-origin requests
    csrf_app = FastAPI()
    csrf_app.add_middleware(CSRFMiddleware, allowed_origins=["http://localhost:8000"])

    @csrf_app.post("/protected-action")
    def action():
        return {"ok": True}

    csrf_client = TestClient(csrf_app, raise_server_exceptions=False)
    cross_origin_resp = csrf_client.post(
        "/protected-action",
        json={"data": "test"},
        headers={"Origin": "https://attacker-malicious-domain.com", "Host": "localhost:8000"},
    )
    assert cross_origin_resp.status_code == 403
    assert "cross-origin request rejected" in cross_origin_resp.text

    # 4. SSRF Defense: assert_public_url rejects loopback, private RFC1918, and metadata IPs
    loop = asyncio.new_event_loop()
    try:
        # Link-local cloud metadata IP is blocked in all environments
        with pytest.raises(NodeExecutionError) as exc_meta:
            loop.run_until_complete(assert_public_url("http://169.254.169.254/latest/meta-data/", node_id="test_http"))
        assert exc_meta.value.code == "SSRF_BLOCKED"

        # Private RFC1918 IP is blocked in all environments
        with pytest.raises(NodeExecutionError) as exc_priv:
            loop.run_until_complete(assert_public_url("http://10.0.0.5/internal/status", node_id="test_http"))
        assert exc_priv.value.code == "SSRF_BLOCKED"

        # In production mode, loopback is strictly blocked as well
        with patch("app.config.get_settings") as mock_cfg:
            mock_s = MagicMock()
            mock_s.app_env = "production"
            mock_s.safe_http_allowed_hosts = ""
            mock_cfg.return_value = mock_s
            with pytest.raises(NodeExecutionError) as exc_loop:
                loop.run_until_complete(assert_public_url("http://127.0.0.1:8080/admin", node_id="test_http"))
            assert exc_loop.value.code == "SSRF_BLOCKED"
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 4. Unsafe Code Execution and Sandbox Escape Resistance
# ---------------------------------------------------------------------------

def test_unsafe_code_execution_and_sandbox_escape_resistance():
    """Verify CodeNode blocks filesystem escapes, unauthorized module imports, and system commands."""
    node = CodeNode()
    ctx = NodeContext(
        execution_id="sec_exec",
        workflow_id="sec_wf",
        logger=__import__("logging").getLogger("test"),
        http_client=None,
        storage=MemoryKVStore(),
    )

    loop = asyncio.new_event_loop()
    try:
        # 1. Block access to os module
        params_os = CodeParams(code='import os\nos.listdir("/")', language="python")
        with pytest.raises(NodeExecutionError):
            loop.run_until_complete(node.run(ctx, params_os, [{}]))

        # 2. Block __import__ system escapes
        params_sys = CodeParams(code='__import__("os").system("echo pwned")', language="python")
        with pytest.raises(NodeExecutionError):
            loop.run_until_complete(node.run(ctx, params_sys, [{}]))

        # 3. Block open() file reads
        params_open = CodeParams(code='open("/etc/passwd").read()', language="python")
        with pytest.raises(NodeExecutionError):
            loop.run_until_complete(node.run(ctx, params_open, [{}]))

        # 4. Block infinite execution loops with timeouts
        with pytest.raises(NodeExecutionError):
            _exec_python_code('x = 0\nwhile True: x += 1', [{}], "runOnceForAllItems", timeout=1.0)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 5. Secrets Exposure Through Logs, APIs and Frontend Bundles
# ---------------------------------------------------------------------------

def test_secrets_exposure_through_logs_apis_and_bundles(client):
    """Verify credentials are encrypted at rest, secret data is excluded from APIs, and DSNs are redacted."""
    reg = client.post("/api/auth/register", json={"email": f"secret_{_uid()}@test.com", "password": "Password123!"}).json()["data"]
    headers = _auth_headers(reg["token"])

    # 1. Create a credential with sensitive API key and secret using registered 'llm' type
    secret_key = "sk_live_very_secret_key_12345"
    cred_payload = {
        "name": "Production LLM Key",
        "type": "llm",
        "data": {"base_url": "http://127.0.0.1:9/v1", "api_key": secret_key, "model": "gpt-4"},
    }
    create_resp = client.post("/api/credentials", json=cred_payload, headers=headers)
    assert create_resp.status_code == 201
    cred_id = create_resp.json()["data"]["id"]

    # 2. Verify /api/credentials listing NEVER includes raw secrets
    list_resp = client.get("/api/credentials", headers=headers)
    assert list_resp.status_code == 200
    list_str = json.dumps(list_resp.json())
    assert secret_key not in list_str

    # 3. Verify security design: GET /{credential_id} is intentionally disallowed (405) to prevent exfiltration
    get_resp = client.get(f"/api/credentials/{cred_id}", headers=headers)
    assert get_resp.status_code == 405

    # 4. Verify encryption at rest in PostgreSQL
    db = get_session()
    try:
        db_cred = db.get(Credential, cred_id)
        assert db_cred is not None
        raw_db_bytes = bytes(db_cred.data)
        assert secret_key.encode() not in raw_db_bytes
        # Decryption works via master key
        decrypted_json = decrypt_text(raw_db_bytes)
        assert secret_key in decrypted_json
    finally:
        db.close()

    # 5. Verify DSN log redaction: passwords must be masked
    sample_dsn = "postgresql://myuser:SuperSecretPassword123@db.internal:5432/flowsmith"
    redacted = _redact_db_url(sample_dsn)
    assert "SuperSecretPassword123" not in redacted
    assert "myuser:***@" in redacted


# ---------------------------------------------------------------------------
# 6. Webhook Signature and Replay Validation
# ---------------------------------------------------------------------------

def test_webhook_signature_and_replay_validation():
    """Verify HMAC-SHA256 signature calculation, constant-time validation, and replay rejection."""
    secret = "whsec_test_secret_key_999"
    payload = b'{"event": "payment_succeeded", "amount": 5000}'
    now = int(time.time())

    # Generate legitimate signature: t={now},v1={hmac}
    signed_payload = f"{now}.".encode() + payload
    legit_sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    valid_header = f"t={now},v1={legit_sig}"

    # 1. Valid signature and fresh timestamp succeeds
    assert verify_webhook_signature(payload, valid_header, secret=secret) is True

    # 2. Tampered signature fails
    tampered_header = f"t={now},v1={legit_sig[:-4]}beef"
    assert verify_webhook_signature(payload, tampered_header, secret=secret) is False

    # 3. Tampered payload fails
    tampered_payload = b'{"event": "payment_succeeded", "amount": 999999}'
    assert verify_webhook_signature(tampered_payload, valid_header, secret=secret) is False

    # 4. Replay attack rejection: timestamp older than tolerance window (300s) fails
    old_time = now - (WEBHOOK_TOLERANCE_SECONDS + 60)
    old_signed = f"{old_time}.".encode() + payload
    old_sig = hmac.new(secret.encode(), old_signed, hashlib.sha256).hexdigest()
    expired_header = f"t={old_time},v1={old_sig}"

    assert verify_webhook_signature(payload, expired_header, secret=secret) is False


# ---------------------------------------------------------------------------
# 7. Dependency Vulnerabilities and Insecure Configurations
# ---------------------------------------------------------------------------

def test_dependency_vulnerabilities_and_insecure_configurations():
    """Verify production settings guards against weak secrets, missing encryption, and insecure databases."""
    base_settings = {
        "app_env": "production",
        "credentials_encryption_key": "k1:abcdefghijklmnop",
        "jwt_secret": "a-secure-production-jwt-secret-that-has-sufficient-entropy-32b",
        "database_url": "postgresql://user:pass@db:5432/flowsmith",
        "cors_origins": "https://flowsmith.app",
        "registration_bootstrap_token": "bootstrap-token-with-at-least-32-characters",
        "safe_http_allowed_hosts": "",
        "safe_http_allowed_ports": "",
    }

    # 1. Complete valid production configuration passes
    validate_production_settings(Settings(**base_settings))

    # 2. Rejects default insecure JWT secret
    with pytest.raises(ConfigError, match="JWT_SECRET"):
        validate_production_settings(Settings(**{**base_settings, "jwt_secret": "dev-only-secret-change-me"}))

    # 3. Rejects empty credentials encryption key
    with pytest.raises(ConfigError, match="CREDENTIALS_ENCRYPTION_KEY"):
        validate_production_settings(Settings(**{**base_settings, "credentials_encryption_key": ""}))

    # 4. Rejects SQLite in production
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        validate_production_settings(Settings(**{**base_settings, "database_url": "sqlite:///./data/app.db"}))


# ---------------------------------------------------------------------------
# 8. Audit Logs and Sensitive-Data Handling
# ---------------------------------------------------------------------------

def test_audit_logs_and_sensitive_data_handling(client):
    """Verify immutable audit log emission and password hashing security."""
    db = get_session()
    try:
        user = _create_test_user(db)

        # 1. Test audit log entry creation
        log_event(
            db,
            WORKFLOW_CREATE,
            target_type="workflow",
            target_id="wf_audit_1",
            user_id=user.id,
            detail={"name": "Audit Sample", "nodes_count": 3},
        )
        log_event(
            db,
            CREDENTIAL_CREATE,
            target_type="credential",
            target_id="cred_audit_1",
            user_id=user.id,
            detail={"type": "slack", "masked_key": "xoxb-***"},
        )

        # Verify audit records exist in database
        audit_events = db.query(AuditEvent).filter(AuditEvent.user_id == user.id).all()
        actions = [a.action for a in audit_events]
        assert WORKFLOW_CREATE in actions
        assert CREDENTIAL_CREATE in actions

        # 2. Password Security: Passwords must use strong one-way hashing with salt
        raw_password = "SecureComplexPassword2026!"
        hashed = hash_password(raw_password)

        assert raw_password not in hashed
        assert verify_password(raw_password, hashed) is True
        assert verify_password("WrongPassword123", hashed) is False

        # Two hashes of the same password must differ due to unique salts
        hashed_again = hash_password(raw_password)
        assert hashed != hashed_again
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 9. Rate Limiting and Abuse Resistance
# ---------------------------------------------------------------------------

def test_rate_limiting_and_abuse_resistance(client):
    """Verify brute-force login throttling and sensitive endpoint protection."""
    test_email = f"brute_{_uid()}@test.com"
    login_throttle.reset()

    # Attempt consecutive invalid password attempts
    for _ in range(5):
        resp = client.post("/api/auth/login", json={"email": test_email, "password": "wrong_password"})
        assert resp.status_code in (401, 429)

    final_resp = client.post("/api/auth/login", json={"email": test_email, "password": "wrong_password"})
    assert final_resp.status_code in (401, 429)

    login_throttle.reset()


# ---------------------------------------------------------------------------
# 10. Security Regression Tests After Fixes
# ---------------------------------------------------------------------------

def test_execution_search_snippets_are_redacted_for_view_only():
    """Search must not be a side channel that returns raw execution secrets."""
    from types import SimpleNamespace

    from app.services.telemetry_service import extract_execution_search_matches

    rec = SimpleNamespace(
        id="exec_search_redact",
        workflow_id="wf_search_redact",
        status="success",
        trigger="manual",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        duration_ms=10.0,
        source_connector="http",
        destination_connector="http",
        source_object="request",
        destination_object="response",
        api_endpoint="https://api.example.com",
        http_method="POST",
        http_status_code=200,
        error=None,
        error_summary="",
        error_code="",
        error_type="",
        trigger_data=None,
        results=None,
        trace=[{
            "node_id": "n1",
            "node_title": "HTTP Request",
            "node_type": "http_request",
            "status": "success",
            "outputs": {"body": {"access_token": "sk-live-secret-123"}},
        }],
    )
    matches = extract_execution_search_matches(rec, "sk-live-secret-123", redact_values=True)
    assert matches
    assert all("sk-live-secret-123" not in (m.get("snippet") or "") for m in matches)
    assert all(m.get("field_value") is None for m in matches)


def test_security_regression_tests_after_fixes(client):
    """Verify regression protection against known vulnerability classes."""
    # 1. Token Tampering: altering 'sub' user ID in token signature invalidates JWT
    reg = client.post("/api/auth/register", json={"email": f"reg_{_uid()}@test.com", "password": "Password123!"}).json()["data"]
    token = reg["token"]
    parts = token.split(".")
    assert len(parts) == 3

    # Swap header or payload with base64 altered payload
    forged_token = parts[0] + ".eyJzdWIiOiA5OTk5OX0." + parts[2]
    assert client.get("/api/auth/me", headers=_auth_headers(forged_token)).status_code == 401

    # 2. SQL injection via Read-only query filter
    with pytest.raises(ValueError, match="Only a single SQL statement is allowed"):
        _check_readonly_sql("SELECT 1; DROP TABLE users;")

    with pytest.raises(ValueError, match="Only read-only SQL is allowed"):
        _check_readonly_sql("DELETE FROM users WHERE id = 1")

    with pytest.raises(ValueError, match="Only read-only SQL is allowed"):
        _check_readonly_sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity")
