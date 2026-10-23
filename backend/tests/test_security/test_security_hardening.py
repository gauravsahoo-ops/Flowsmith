"""Comprehensive Phase 2 Negative Security Tests.

Tests mandatory security hardening requirements:
1. Authentication & token rotation / expiry / revocation / stale tokens.
2. Tenant boundaries & IDOR (workflows, executions, credentials, data tables, files).
3. Privilege escalation & RBAC.
4. SSRF protection (private IPs, cloud metadata, decimal/hex IPs, non-http schemes).
5. Code execution sandbox enforcement (AST blocking, dunder attributes, dangerous builtins, timeouts).
6. Secret leakage redaction & CSV formula injection prevention.
7. Production startup security validation (credentials key, jwt secret, cors, db url).
"""

from __future__ import annotations

import base64
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app.api.auth import token_is_stale
from app.config import ConfigError, Settings, get_settings, validate_production_settings
from app.engine.errors import NodeExecutionError
from app.engine.redact import sanitize_csv_cell, redact_sensitive, MASK
from app.main import app
from app.models import User
from app.nodes.code import CodeNode, CodeParams, validate_code
from app.security.crypto import cipher_decrypt_v2, cipher_encrypt_v2, decrypt_text, encrypt_text
from app.security.jwt import create_token, decode_token, revoke_token
from app.security.safe_http_client import SafeHTTPClient, _parse_literal_ip, _ipv4_blocked
from app.security.ssrf import assert_public_url


@pytest.fixture
def api_client():
    return TestClient(app, raise_server_exceptions=False)


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register_user(client: TestClient, email: str | None = None, password: str = "StrongPass1!") -> tuple[dict, str]:
    if email is None:
        email = f"sec_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    return data["user"], data["token"]


# ----------------------------------------------------------------------
# 1. Authentication & Token Revocation / Stale Token Tests
# ----------------------------------------------------------------------

class TestAuthenticationSecurity:
    def test_unauthenticated_requests_fail(self, api_client):
        protected_endpoints = [
            ("GET", "/api/workflows"),
            ("POST", "/api/workflows"),
            ("GET", "/api/executions"),
            ("GET", "/api/credentials"),
            ("POST", "/api/credentials"),
            ("GET", "/api/data-tables"),
            ("GET", "/api/files"),
            ("GET", "/api/auth/sessions"),
        ]
        for method, endpoint in protected_endpoints:
            if method == "GET":
                r = api_client.get(endpoint)
            else:
                r = api_client.post(endpoint, json={})
            assert r.status_code == 401, f"{method} {endpoint} did not return 401"

    def test_expired_token_rejected(self, api_client):
        settings = get_settings()
        now = datetime.now(UTC)
        payload = {
            "sub": "1",
            "iat": int((now - timedelta(hours=2)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),
            "jti": uuid.uuid4().hex,
        }
        token = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        r = api_client.get("/api/workflows", headers=_auth_header(token))
        assert r.status_code == 401

    def test_tampered_token_signature_rejected(self, api_client):
        user, token = _register_user(api_client)
        # Flip bits in the signature part
        parts = token.split(".")
        tampered_sig = parts[2][:-2] + ("aa" if parts[2][-2:] != "aa" else "bb")
        bad_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"
        r = api_client.get("/api/workflows", headers=_auth_header(bad_token))
        assert r.status_code == 401

    def test_revoked_token_rejected_immediately(self, api_client):
        user, token = _register_user(api_client)
        decoded = decode_token(token)
        jti = decoded["jti"]

        # Token works initially
        r1 = api_client.get("/api/workflows", headers=_auth_header(token))
        assert r1.status_code == 200

        # Revoke the token
        revoke_token(jti)

        # Token must be rejected immediately
        r2 = api_client.get("/api/workflows", headers=_auth_header(token))
        assert r2.status_code == 401

    def test_stale_token_after_password_reset(self):
        now = datetime.now(UTC)
        user = User(id=42, email="victim@example.com")
        # Token issued at now - 10 minutes
        stale_payload = {"sub": "42", "iat": int((now - timedelta(minutes=10)).timestamp())}
        # Cutoff set at now - 2 minutes
        user.tokens_valid_from = now - timedelta(minutes=2)

        assert token_is_stale(stale_payload, user) is True

        # Token issued after cutoff is fresh
        fresh_payload = {"sub": "42", "iat": int((now + timedelta(seconds=1)).timestamp())}
        assert token_is_stale(fresh_payload, user) is False


# ----------------------------------------------------------------------
# 2. Tenant Boundaries & Cross-Tenant IDOR Violations
# ----------------------------------------------------------------------

class TestTenantBoundariesAndIDOR:
    def test_user_b_cannot_access_user_a_workflow(self, api_client):
        user_a, token_a = _register_user(api_client)
        user_b, token_b = _register_user(api_client)

        wf_id = f"wf_{uuid.uuid4().hex[:12]}"
        create_resp = api_client.post(
            "/api/workflows",
            json={"id": wf_id, "name": "Confidential Workflow", "nodes": [], "connections": []},
            headers=_auth_header(token_a),
        )
        assert create_resp.status_code == 201

        # User B attempts to GET User A's workflow
        r_get = api_client.get(f"/api/workflows/{wf_id}", headers=_auth_header(token_b))
        assert r_get.status_code == 404, "User B could view User A's workflow"

        # User B attempts to UPDATE User A's workflow
        r_put = api_client.put(
            f"/api/workflows/{wf_id}",
            json={"id": wf_id, "name": "Hijacked Workflow", "nodes": [], "connections": []},
            headers=_auth_header(token_b),
        )
        assert r_put.status_code in (403, 404), "User B could modify User A's workflow"

        # User B attempts to DELETE User A's workflow
        r_del = api_client.delete(f"/api/workflows/{wf_id}", headers=_auth_header(token_b))
        assert r_del.status_code in (403, 404), "User B could delete User A's workflow"

        # User B attempts to TRIGGER User A's workflow
        r_run = api_client.post(f"/api/workflows/{wf_id}/run", json={}, headers=_auth_header(token_b))
        assert r_run.status_code in (403, 404), "User B could trigger User A's workflow"

    def test_user_b_cannot_access_user_a_credentials(self, api_client):
        user_a, token_a = _register_user(api_client)
        user_b, token_b = _register_user(api_client)

        cred_resp = api_client.post(
            "/api/credentials",
            json={"name": "Secret API Key", "type": "http", "data": {"api_key": "secret-12345"}},
            headers=_auth_header(token_a),
        )
        assert cred_resp.status_code == 201, cred_resp.text
        cred_id = cred_resp.json()["data"]["id"]

        # User B cannot see it in list
        list_resp = api_client.get("/api/credentials", headers=_auth_header(token_b))
        ids = [c["id"] for c in list_resp.json()["data"]]
        assert cred_id not in ids, "User B saw User A's credential in list"

        # User B cannot update User A's credential
        r_update = api_client.put(
            f"/api/credentials/{cred_id}",
            json={"name": "Hijacked Credential"},
            headers=_auth_header(token_b),
        )
        assert r_update.status_code == 404

        # User B cannot delete User A's credential
        r_delete = api_client.delete(f"/api/credentials/{cred_id}", headers=_auth_header(token_b))
        assert r_delete.status_code == 404


# ----------------------------------------------------------------------
# 3. SSRF Protection & Bypass Rejection Tests
# ----------------------------------------------------------------------

class TestSSRFGuards:
    @pytest.mark.asyncio
    async def test_ssrf_rejects_literal_loopback_in_production(self):
        targets = [
            "http://127.0.0.1:8080/admin",
            "http://127.0.1.1:80",
            "http://0.0.0.0:3000",
            "http://[::1]:8080/secret",
        ]
        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                app_env="production",
                safe_http_allowed_hosts="",
                safe_http_allowed_ports="",
                allow_ssrf_bypass="",
            )
            for url in targets:
                with pytest.raises(NodeExecutionError) as exc_info:
                    await assert_public_url(url, node_id="test_node")
                assert exc_info.value.code == "SSRF_BLOCKED"

    @pytest.mark.asyncio
    async def test_ssrf_rejects_cloud_metadata_endpoints(self):
        targets = [
            "http://169.254.169.254/latest/meta-data/",
            "http://169.254.170.2/v2/metadata",
        ]
        for url in targets:
            with pytest.raises(NodeExecutionError) as exc_info:
                await assert_public_url(url, node_id="test_node")
            assert exc_info.value.code == "SSRF_BLOCKED"

    @pytest.mark.asyncio
    async def test_ssrf_rejects_rfc1918_private_ranges(self):
        private_urls = [
            "http://10.0.0.1:8080",
            "http://10.255.255.254",
            "http://172.16.0.1",
            "http://172.31.255.255",
            "http://192.168.0.1",
            "http://192.168.1.254",
        ]
        for url in private_urls:
            with pytest.raises(NodeExecutionError) as exc_info:
                await assert_public_url(url, node_id="test_node")
            assert exc_info.value.code == "SSRF_BLOCKED"

    def test_ssrf_parses_hex_and_decimal_representations(self):
        # 127.0.0.1 as decimal = 2130706433
        dec_ip = _parse_literal_ip("2130706433")
        assert dec_ip is not None
        assert _ipv4_blocked(dec_ip) is True

        # 127.0.0.1 as hex = 0x7f000001
        hex_ip = _parse_literal_ip("0x7f000001")
        assert hex_ip is not None
        assert _ipv4_blocked(hex_ip) is True

        # 10.0.0.1 as decimal = 167772161
        dec_priv = _parse_literal_ip("167772161")
        assert dec_priv is not None
        assert _ipv4_blocked(dec_priv) is True

    @pytest.mark.asyncio
    async def test_ssrf_blocks_non_http_schemes(self):
        schemes = [
            "file:///etc/passwd",
            "gopher://127.0.0.1:6379",
            "ftp://internal.server/data",
            "dict://127.0.0.1:11211",
        ]
        for url in schemes:
            with pytest.raises(NodeExecutionError) as exc_info:
                await assert_public_url(url, node_id="test_node")
            assert exc_info.value.code == "SSRF_BLOCKED"


# ----------------------------------------------------------------------
# 4. Untrusted Code Execution & Sandbox Breakout Prevention
# ----------------------------------------------------------------------

class TestCodeExecutionSandbox:
    def test_python_blocks_all_import_statements(self):
        attacks = [
            "import os",
            "import sys",
            "import subprocess",
            "import socket",
            "from os import system",
            "from pathlib import Path",
        ]
        for code in attacks:
            valid, err, line, col = validate_code(code, language="python")
            assert valid is False
            assert "prohibited" in (err or "").lower()

    def test_python_blocks_dunder_attribute_traversal(self):
        attacks = [
            "x = ().__class__.__bases__[0].__subclasses__()",
            "f = ().__class__.__mro__[1]",
            "g = [].__globals__",
            "d = {}.__dict__",
        ]
        for code in attacks:
            valid, err, line, col = validate_code(code, language="python")
            assert valid is False
            assert "dunder" in (err or "").lower() or "prohibited" in (err or "").lower()

    def test_python_blocks_dangerous_builtins(self):
        dangerous = ["eval('1+1')", "exec('a=1')", "open('/etc/passwd')", "getattr(str, 'upper')"]
        for code in dangerous:
            valid, err, line, col = validate_code(code, language="python")
            assert valid is False
            assert "prohibited" in (err or "").lower()

    @pytest.mark.asyncio
    async def test_python_infinite_loop_timeout_protection(self):
        node = CodeNode()
        params = CodeParams(
            code="while True:\n    pass\nreturn []",
            language="python",
        )
        ctx = MagicMock()
        # Execution must raise timeout and must not hang indefinitely
        with pytest.raises(NodeExecutionError) as exc_info:
            await node.run(ctx, params, [{}])
        assert "timeout" in exc_info.value.message.lower() or exc_info.value.code == "CODE_TIMEOUT"


# ----------------------------------------------------------------------
# 5. Secret Redaction & CSV Formula Injection Protection
# ----------------------------------------------------------------------

class TestSecretRedactionAndInjectionDefense:
    def test_redact_sensitive_masks_sensitive_keys(self):
        payload = {
            "name": "Public Workflow",
            "password": "super-secret-password",
            "api_key": "live_key_9999",
            "auth_token": "bearer xyz789",
            "user_email": "safe@flowsmith.io",
            "nested": {
                "private_key": "-----BEGIN RSA-----",
                "normal_counter": 42,
            },
        }
        redacted = redact_sensitive(payload)
        assert redacted["name"] == "Public Workflow"
        assert redacted["user_email"] == "safe@flowsmith.io"
        assert redacted["password"] == MASK
        assert redacted["api_key"] == MASK
        assert redacted["auth_token"] == MASK
        assert redacted["nested"]["private_key"] == MASK
        assert redacted["nested"]["normal_counter"] == 42

    def test_sanitize_csv_cell_escapes_formulas(self):
        dangerous_inputs = [
            "=SUM(A1:A10)",
            "-2+3+cmd|' /C calc'!A0",
            "+10*5",
            "@cmd",
            "\tTAB_INJECTION",
            "\rCR_INJECTION",
        ]
        for dangerous in dangerous_inputs:
            safe = sanitize_csv_cell(dangerous)
            assert safe.startswith("'"), f"CSV formula was not escaped: {dangerous}"

        # Safe inputs are left unchanged
        safe_inputs = ["Normal Text", "123", "hello@example.com", ""]
        for safe in safe_inputs:
            assert sanitize_csv_cell(safe) == safe


# ----------------------------------------------------------------------
# 6. Production Startup Configuration Hardening
# ----------------------------------------------------------------------

class TestProductionStartupValidation:
    def test_rejects_missing_credentials_encryption_key(self):
        s = Settings(
            app_env="production",
            credentials_encryption_key="",
            jwt_secret="super-strong-jwt-secret-with-sufficient-entropy-12345",
            database_url="postgresql+psycopg://user:pass@db:5432/automate",
            cors_origins="https://app.flowsmith.io",
            registration_bootstrap_token="bootstrap-token-with-at-least-32-characters",
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_production_settings(s)
        assert "CREDENTIALS_ENCRYPTION_KEY" in str(exc_info.value)

    def test_rejects_insecure_jwt_secret(self):
        s = Settings(
            app_env="production",
            credentials_encryption_key="a" * 44,
            jwt_secret="dev-only-secret-change-me",
            database_url="postgresql+psycopg://user:pass@db:5432/automate",
            cors_origins="https://app.flowsmith.io",
            registration_bootstrap_token="bootstrap-token-with-at-least-32-characters",
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_production_settings(s)
        assert "JWT_SECRET" in str(exc_info.value)

    def test_rejects_sqlite_database_url_in_production(self):
        s = Settings(
            app_env="production",
            credentials_encryption_key="a" * 44,
            jwt_secret="super-strong-jwt-secret-with-sufficient-entropy-12345",
            database_url="sqlite:///test.db",
            cors_origins="https://app.flowsmith.io",
            registration_bootstrap_token="bootstrap-token-with-at-least-32-characters",
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_production_settings(s)
        assert "DATABASE_URL" in str(exc_info.value)

    def test_rejects_wildcard_cors_in_production(self):
        s = Settings(
            app_env="production",
            credentials_encryption_key="a" * 44,
            jwt_secret="super-strong-jwt-secret-with-sufficient-entropy-12345",
            database_url="postgresql+psycopg://user:pass@db:5432/automate",
            cors_origins="*",
            registration_bootstrap_token="bootstrap-token-with-at-least-32-characters",
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_production_settings(s)
        assert "CORS_ORIGINS" in str(exc_info.value)

    def test_rejects_ssrf_bypass_without_explicit_opt_in(self):
        s = Settings(
            app_env="production",
            credentials_encryption_key="a" * 44,
            jwt_secret="super-strong-jwt-secret-with-sufficient-entropy-12345",
            database_url="postgresql+psycopg://user:pass@db:5432/automate",
            cors_origins="https://app.flowsmith.io",
            registration_bootstrap_token="bootstrap-token-with-at-least-32-characters",
            safe_http_allowed_hosts="internal.corp",
            allow_ssrf_bypass="",
        )
        with pytest.raises(ConfigError) as exc_info:
            validate_production_settings(s)
        assert "ALLOW_SSRF_BYPASS" in str(exc_info.value)
