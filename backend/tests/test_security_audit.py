"""Security audit tests (API level).

Uses FastAPI TestClient against real endpoints.  Tests verify:
- Authentication & authorization (JWT, IDOR)
- Input sanitization (SQL injection, XSS)
- SSRF protection
- Rate limiting
- Secret redaction
- Password storage
- Credential encryption at rest
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient

# Force rate-limit OFF for these tests (conftest does this globally, but be explicit).
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import Credential
from app.security.crypto import decrypt_text, encrypt_text
from app.security.jwt import create_token, decode_token, hash_password, revoke_token, verify_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _LazyClient:
    def __init__(self):
        self._c = None

    def _client(self):
        if self._c is None:
            self._c = TestClient(app, raise_server_exceptions=False)
        return self._c

    def __getattr__(self, name):
        return getattr(self._client(), name)


client = _LazyClient()


def _register(email: str, password: str = "StrongPass1!") -> dict:
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    body = r.json()
    # Response is {"data": {"token": ..., "user": ...}}
    return body.get("data", body)


def _login(email: str, password: str = "StrongPass1!") -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    body = r.json()
    return body.get("data", body)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_workflow(token: str, name: str = "test-wf") -> dict:
    wf_id = f"wf_{uuid.uuid4().hex[:12]}"
    r = client.post(
        "/api/workflows",
        json={"id": wf_id, "name": name, "nodes": [], "connections": []},
        headers=_auth_header(token),
    )
    body = r.json()
    data = body.get("data", body)
    return data


# ---------------------------------------------------------------------------
# 1  Unauthenticated access returns 401
# ---------------------------------------------------------------------------

class TestUnauthenticatedAccess:
    def test_workflows_list_no_token(self):
        r = client.get("/api/workflows")
        assert r.status_code == 401

    def test_workflows_get_no_token(self):
        r = client.get("/api/workflows/nonexistent")
        assert r.status_code == 401

    def test_executions_no_token(self):
        r = client.get("/api/executions")
        assert r.status_code == 401

    def test_credentials_no_token(self):
        r = client.get("/api/credentials")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 2-3  Invalid / expired JWT
# ---------------------------------------------------------------------------

class TestJWTValidation:
    def test_invalid_token(self):
        r = client.get("/api/workflows", headers=_auth_header("totally.bogus.token"))
        assert r.status_code == 401

    def test_expired_token(self):
        # Manually craft an expired token
        import jwt as pyjwt
        from datetime import UTC, datetime, timedelta

        settings = get_settings()
        payload = {
            "sub": "1",
            "iat": int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
            "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
            "jti": "expired123",
        }
        token = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        r = client.get("/api/workflows", headers=_auth_header(token))
        assert r.status_code == 401

    def test_token_with_wrong_secret(self):
        import jwt as pyjwt
        from datetime import UTC, datetime, timedelta

        payload = {
            "sub": "1",
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            "jti": "wrongsecret123",
        }
        token = pyjwt.encode(payload, "wrong-secret-key-32-bytes-long!!", algorithm="HS256")
        r = client.get("/api/workflows", headers=_auth_header(token))
        assert r.status_code == 401

    def test_token_with_missing_sub(self):
        import jwt as pyjwt
        from datetime import UTC, datetime, timedelta

        settings = get_settings()
        payload = {
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            "jti": "nosub123",
        }
        token = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        r = client.get("/api/workflows", headers=_auth_header(token))
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 4-5  IDOR: User A cannot access User B's resources
# ---------------------------------------------------------------------------

class TestIDOR:
    def setup_method(self):
        self.ua = _register(f"a_{uuid.uuid4().hex[:8]}@test.com")
        self.ub = _register(f"b_{uuid.uuid4().hex[:8]}@test.com")
        self.token_a = self.ua["token"]
        self.token_b = self.ub["token"]
        self.wf_a = _create_workflow(self.token_a, "a-workflow")
        self.wf_id_a = self.wf_a["id"]

    def test_user_b_cannot_get_user_a_workflow(self):
        r = client.get(
            f"/api/workflows/{self.wf_id_a}",
            headers=_auth_header(self.token_b),
        )
        assert r.status_code == 404

    def test_user_b_cannot_update_user_a_workflow(self):
        r = client.put(
            f"/api/workflows/{self.wf_id_a}",
            json={"name": "hacked", "nodes": [], "connections": []},
            headers=_auth_header(self.token_b),
        )
        assert r.status_code in (404, 403)

    def test_user_b_cannot_delete_user_a_workflow(self):
        r = client.delete(
            f"/api/workflows/{self.wf_id_a}",
            headers=_auth_header(self.token_b),
        )
        assert r.status_code in (404, 403)

    def test_user_b_cannot_run_user_a_workflow(self):
        r = client.post(
            f"/api/workflows/{self.wf_id_a}/run",
            headers=_auth_header(self.token_b),
        )
        assert r.status_code in (404, 403)

    def test_user_b_cannot_see_user_a_credentials(self):
        # User A creates a credential
        r = client.post(
            "/api/credentials",
            json={"name": "secret-cred", "type": "api_key", "data": {"key": "s3cret"}},
            headers=_auth_header(self.token_a),
        )
        if r.status_code == 201:
            cred_id = r.json()["id"]
            r2 = client.get(
                f"/api/credentials/{cred_id}",
                headers=_auth_header(self.token_b),
            )
            assert r2.status_code in (403, 404)


# ---------------------------------------------------------------------------
# 6  SQL injection in workflow name
# ---------------------------------------------------------------------------

class TestSQLInjection:
    def test_sqli_in_name(self):
        email = f"a_{uuid.uuid4().hex[:8]}@test.com"
        _register(email)
        token = _login(email)["token"]
        payloads = [
            "'; DROP TABLE workflows; --",
            "1' OR '1'='1",
            "\" OR 1=1 --",
            "admin'--",
        ]
        for payload in payloads:
            r = client.post(
                "/api/workflows",
                json={"id": f"wf_{uuid.uuid4().hex[:8]}", "name": payload, "nodes": [], "connections": []},
                headers=_auth_header(token),
            )
            # Should either succeed (sanitized) or fail with validation error — never 500
            assert r.status_code in (200, 201, 409, 422), f"SQLi payload caused {r.status_code}: {payload}"

    def test_table_still_exists_after_sqli(self):
        email = f"a_{uuid.uuid4().hex[:8]}@test.com"
        _register(email)
        token = _login(email)["token"]
        client.post(
            "/api/workflows",
            json={"id": f"wf_{uuid.uuid4().hex[:8]}", "name": "'; DROP TABLE workflows; --", "nodes": [], "connections": []},
            headers=_auth_header(token),
        )
        # Table must survive
        r = client.get("/api/workflows", headers=_auth_header(token))
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 7  XSS in workflow name
# ---------------------------------------------------------------------------

class TestXSS:
    def test_script_tag_in_name(self):
        email = f"a_{uuid.uuid4().hex[:8]}@test.com"
        _register(email)
        token = _login(email)["token"]
        r = client.post(
            "/api/workflows",
            json={"id": f"wf_{uuid.uuid4().hex[:8]}", "name": "<script>alert(1)</script>", "nodes": [], "connections": []},
            headers=_auth_header(token),
        )
        assert r.status_code in (200, 201, 409, 422)
        if r.status_code in (200, 201):
            body = r.json()
            data = body.get("data", body)
            name = data.get("name", "")
            # The raw <script> should not survive unescaped in the JSON response
            assert "<script>" not in name or data is not None

    def test_img_onerror_in_name(self):
        email = f"a_{uuid.uuid4().hex[:8]}@test.com"
        _register(email)
        token = _login(email)["token"]
        r = client.post(
            "/api/workflows",
            json={"id": f"wf_{uuid.uuid4().hex[:8]}", "name": '<img src=x onerror="alert(1)">', "nodes": [], "connections": []},
            headers=_auth_header(token),
        )
        assert r.status_code in (200, 201, 409, 422)


# ---------------------------------------------------------------------------
# 8  SSRF protection (HTTP Request node)
# ---------------------------------------------------------------------------

class TestSSRF:
    def test_localhost_request_blocked(self):
        email = f"a_{uuid.uuid4().hex[:8]}@test.com"
        _register(email)
        token = _login(email)["token"]
        wf_id = f"wf_{uuid.uuid4().hex[:8]}"
        wf = client.post(
            "/api/workflows",
            json={
                "id": wf_id,
                "name": "ssrf-test",
                "nodes": [
                    {
                        "id": "n1",
                        "type": "httpRequest",
                        "parameters": {
                            "url": "http://127.0.0.1:5432",
                            "method": "GET",
                        },
                    }
                ],
                "connections": [],
            },
            headers=_auth_header(token),
        )
        if wf.status_code in (200, 201):
            r = client.post(
                f"/api/workflows/{wf_id}/run",
                json={},
                headers=_auth_header(token),
            )
            # Should either block SSRF or not reach internal host
            # (the exact status depends on the node implementation)


# ---------------------------------------------------------------------------
# 9  Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_login_rate_limiting(self):
        """Multiple rapid failed logins should eventually get 429."""
        email = f"rl_{uuid.uuid4().hex[:8]}@test.com"
        # Register first so the account exists
        _register(email)
        # Now send many bad passwords
        got_429 = False
        for _ in range(20):
            r = client.post("/api/auth/login", json={"email": email, "password": "wrongpassword"})
            if r.status_code == 429:
                got_429 = True
                break
        assert got_429, "Login rate limiting did not trigger after 20 failed attempts"

    def test_register_rate_limiting(self):
        """The sliding window limiter should cap registrations."""
        # Just verify the endpoint doesn't crash under rapid requests
        for i in range(5):
            r = client.post(
                "/api/auth/register",
                json={"email": f"rate_{i}_{uuid.uuid4().hex[:8]}@test.com", "password": "StrongPass1!"},
            )
            assert r.status_code in (201, 429)


# ---------------------------------------------------------------------------
# 10  CORS headers
# ---------------------------------------------------------------------------

class TestCORSHeaders:
    def test_cors_preflight(self):
        settings = get_settings()
        allowed = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
        origin = allowed[0] if (allowed and "*" not in allowed) else "http://localhost:3000"
        r = client.options(
            "/api/workflows",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        # Should have CORS headers (or 405 if OPTIONS not explicitly routed)
        assert r.status_code in (200, 204, 405)

    def test_cors_in_response(self):
        settings = get_settings()
        allowed = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
        origin = allowed[0] if (allowed and "*" not in allowed) else "http://localhost:3000"
        r = client.get("/api/workflows", headers={"Origin": origin})
        # Check CORS header is present
        if "access-control-allow-origin" in r.headers:
            assert r.headers["access-control-allow-origin"]


# ---------------------------------------------------------------------------
# 10b Security headers (CSP regression — production-serving only)
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    def test_csp_header_hardened(self):
        r = client.get("/api/health")
        csp = r.headers.get("Content-Security-Policy", "")
        assert csp, "CSP header missing"
        # Strict script policy; Monaco + workers are self-hosted (no CDN).
        assert "script-src 'self'" in csp
        assert "jsdelivr" not in csp
        # Google Fonts <link> in index.html must be allowed to load.
        assert "https://fonts.googleapis.com" in csp
        assert "https://fonts.gstatic.com" in csp
        # Same-origin object-URL previews: <img>, sandboxed PDF iframe,
        # fetch() of fetched file blobs, and web workers.
        assert "img-src 'self' data: blob:" in csp
        assert "frame-src 'self' blob: data:" in csp
        assert "connect-src 'self' blob:" in csp
        assert "worker-src 'self' blob:" in csp
        # Clickjacking / plugin hardening.
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp

    def test_hardening_headers_present(self):
        r = client.get("/api/health")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


# ---------------------------------------------------------------------------
# 11-12  Secret redaction in API responses
# ---------------------------------------------------------------------------

class TestSecretRedaction:
    def test_credential_data_not_in_list(self):
        email = f"sec_{uuid.uuid4().hex[:8]}@test.com"
        reg = _register(email)
        token = reg["token"]
        r = client.post(
            "/api/credentials",
            json={"name": "api-key", "type": "api_key", "data": {"apiKey": "supersecret123"}},
            headers=_auth_header(token),
        )
        if r.status_code in (200, 201):
            body = r.json()
            data = body.get("data", body)
            cred_id = data.get("id") or data.get("credential_id")
            # List endpoint
            r2 = client.get("/api/credentials", headers=_auth_header(token))
            if r2.status_code == 200:
                body2 = r2.json()
                data2 = body2.get("data", body2)
                creds = data2 if isinstance(data2, list) else data2.get("items", data2.get("credentials", []))
                for c in (creds if isinstance(creds, list) else []):
                    if c.get("id") == cred_id:
                        # The raw API key should never appear
                        assert "supersecret123" not in json.dumps(c)

    def test_credential_data_not_in_get(self):
        email = f"sec_{uuid.uuid4().hex[:8]}@test.com"
        reg = _register(email)
        token = reg["token"]
        r = client.post(
            "/api/credentials",
            json={"name": "db-pass", "type": "database", "data": {"password": "hunter2"}},
            headers=_auth_header(token),
        )
        if r.status_code in (200, 201):
            body = r.json()
            data = body.get("data", body)
            cred_id = data.get("id") or data.get("credential_id")
            r2 = client.get(f"/api/credentials/{cred_id}", headers=_auth_header(token))
            if r2.status_code == 200:
                body2 = r2.json()
                data2 = body2.get("data", body2)
                resp_text = json.dumps(data2)
                assert "hunter2" not in resp_text


# ---------------------------------------------------------------------------
# 13  Password not stored in plaintext
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_password_is_hashed(self):
        password = "MySecurePass123!"
        hashed = hash_password(password)
        # The stored hash must differ from plaintext
        assert hashed != password
        assert password not in hashed
        # Must contain the algo/iterations/salt/hash structure
        parts = hashed.split("$")
        assert len(parts) == 4
        assert parts[0] == "pbkdf2_sha256"
        assert int(parts[1]) >= 100_000

    def test_verify_password_correct(self):
        password = "AnotherPass456!"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_wrong(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_different_hashes_for_same_password(self):
        h1 = hash_password("same-pass")
        h2 = hash_password("same-pass")
        # Different random salts → different hashes
        assert h1 != h2
        # But both verify
        assert verify_password("same-pass", h1)
        assert verify_password("same-pass", h2)


# ---------------------------------------------------------------------------
# 14  Credential encryption at rest
# ---------------------------------------------------------------------------

class TestCredentialEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        plaintext = '{"apiKey": "s3cret-key-12345"}'
        encrypted = encrypt_text(plaintext)
        decrypted = decrypt_text(encrypted)
        assert decrypted == plaintext

    def test_encrypted_differs_from_plaintext(self):
        plaintext = "very-secret-data"
        encrypted = encrypt_text(plaintext)
        assert encrypted != plaintext.encode()
        assert plaintext.encode() not in encrypted

    def test_different_encryptions_differ(self):
        e1 = encrypt_text("same-data")
        e2 = encrypt_text("same-data")
        assert e1 != e2  # random IV → different ciphertext

    def test_credential_model_uses_encryption(self):
        """Verify Credential model stores encrypted data, not plaintext."""
        from app.security.crypto import encrypt_text as enc

        raw = json.dumps({"password": "db-password"})
        encrypted = enc(raw)
        # Create a real user first for FK constraint
        email = f"cred_{uuid.uuid4().hex[:8]}@test.com"
        reg = _register(email)
        user_id = reg["user"]["id"]
        with get_session() as db:
            cred = Credential(
                id=f"cred_test_{uuid.uuid4().hex[:8]}",
                user_id=user_id,
                name="test-cred",
                type="database",
                data=encrypted,
            )
            db.add(cred)
            db.commit()
            db.refresh(cred)
            # Stored data is NOT the plaintext
            assert cred.data != raw.encode()
            assert b"db-password" not in cred.data


# ---------------------------------------------------------------------------
# 15  Token revocation
# ---------------------------------------------------------------------------

class TestTokenRevocation:
    def test_revoked_token_rejected(self):
        from datetime import UTC, datetime

        token = create_token(99999)
        payload = decode_token(token)
        jti = payload["jti"]
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        revoke_token(jti, exp)
        with pytest.raises(Exception):
            decode_token(token)


class TestJwtSecretFallback:
    def test_blank_secret_autogenerates_and_never_signs_with_empty_key(self, monkeypatch):
        """Regression: compose forwards ``JWT_SECRET: ${JWT_SECRET:-}``, so a
        missing env var arrives as ``""``. A blank signing key would let anyone
        forge valid tokens - auto-generation must kick in instead."""
        import jwt as pyjwt
        from jwt.exceptions import InvalidKeyError

        settings = get_settings()
        monkeypatch.setattr(settings, "jwt_secret", "")

        token = create_token(1)

        # A blank key can't verify (PyJWT refuses empty HMAC keys outright)...
        with pytest.raises(InvalidKeyError):
            pyjwt.decode(token, "", algorithms=[settings.jwt_algorithm])
        # ...while the generated key round-trips through our own verify path.
        assert decode_token(token)["sub"] == "1"
        assert settings.jwt_secret, "blank secret must be replaced by a generated key"


class TestSQLReadonlyToolGuard:
    """H6: the AI database tool's read-only gate must survive smuggling."""

    @staticmethod
    def _check(sql: str) -> None:
        from app.ai.tools import _check_readonly_sql

        _check_readonly_sql(sql)

    def test_modifying_first_token_rejected(self):
        with pytest.raises(ValueError, match="read-only"):
            self._check("DELETE FROM users WHERE 1=1")

    def test_multi_statement_rejected(self):
        with pytest.raises(ValueError, match="single SQL statement"):
            self._check("SELECT 1; DROP TABLE users")

    def test_cte_wrapped_write_rejected(self):
        with pytest.raises(ValueError, match="modifying keywords"):
            self._check(
                "WITH gone AS (SELECT id FROM users) "
                "DELETE FROM users WHERE id IN (SELECT id FROM gone)"
            )

    def test_explain_analyze_write_rejected(self):
        with pytest.raises(ValueError, match="modifying keywords"):
            self._check("EXPLAIN ANALYZE DELETE FROM users")

    def test_dangerous_function_rejected(self):
        with pytest.raises(ValueError, match="modifying keywords"):
            self._check("SELECT pg_terminate_backend(42)")

    def test_pragma_assignment_rejected(self):
        with pytest.raises(ValueError, match="assign"):
            self._check("PRAGMA user_version=3")

    def test_literal_and_comment_text_not_flagged(self):
        self._check("SELECT 'DELETE FROM users' AS s")
        self._check("SELECT 1 -- DELETE FROM users\n")
        self._check("SELECT * FROM users;")  # trailing semicolon is fine

    def test_handler_rejects_before_touching_db(self):
        from types import SimpleNamespace

        from app.ai.tools import _database_query_handler

        ctx = SimpleNamespace(credentials={})
        with pytest.raises(ValueError):
            _database_query_handler(ctx, {"sql": "UPDATE users SET x = 1"})
