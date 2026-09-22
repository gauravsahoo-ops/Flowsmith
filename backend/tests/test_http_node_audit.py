"""Audit test suite: HTTP Request node + credential system.

24 targeted tests covering HTTP methods, auth, expression resolution,
SSRF protection, error handling, and credential encryption/decryption.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.engine.errors import NodeExecutionError
from app.engine.node_base import MemoryKVStore, NodeContext
from app.engine import expressions
from app.nodes.http_request import HTTPRequestNode, HTTPRequestParams, parse_curl


# ── Mock HTTP Server ────────────────────────────────────────────────

class _MockHandler(BaseHTTPRequestHandler):
    """Routes GET/POST/PATCH/DELETE and echoes request details as JSON."""

    def log_message(self, *args):
        pass  # suppress request logs during tests

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _respond(self, status: int, body: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def _get_headers_dict(self) -> dict[str, str]:
        return {k.lower(): v for k, v in self.headers.items()}

    def do_GET(self):
        body = self._read_body()
        self._respond(200, {
            "method": "GET", "path": self.path,
            "headers": self._get_headers_dict(),
            "body": body.decode() if body else "",
        })

    def do_POST(self):
        body = self._read_body()
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body.decode(errors="replace")}
        self._respond(201, {
            "method": "POST", "path": self.path,
            "headers": self._get_headers_dict(), "body": parsed,
        })

    def do_PATCH(self):
        body = self._read_body()
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body.decode(errors="replace")}
        self._respond(200, {
            "method": "PATCH", "path": self.path,
            "headers": self._get_headers_dict(), "body": parsed,
        })

    def do_DELETE(self):
        self._respond(200, {
            "method": "DELETE", "path": self.path,
            "headers": self._get_headers_dict(),
        })


class _TimeoutHandler(BaseHTTPRequestHandler):
    """Sleeps 5 seconds before responding — used for timeout tests."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        time.sleep(5)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())


class _Error4xxHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        self.send_response(422)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Unprocessable"}).encode())
    def do_POST(self):
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())


class _Error5xxHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Service Unavailable"}).encode())


class _FormEchoHandler(BaseHTTPRequestHandler):
    """Echoes raw body and content-type for form/multipart tests."""

    def log_message(self, *args):
        pass
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        ct = self.headers.get("Content-Type", "")
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "method": "POST",
            "content_type": ct,
            "body": body.decode(errors="replace"),
            "headers": dict(self.headers),
        }).encode())


class _LargeResponseHandler(BaseHTTPRequestHandler):
    """Returns a ~1MB JSON response."""

    def log_message(self, *args):
        pass
    def do_GET(self):
        data = {"data": "x" * (1024 * 1024)}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


class _TextHandler(BaseHTTPRequestHandler):
    """Returns plain text."""

    def log_message(self, *args):
        pass
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"hello plain text")


class _LinkPaginationHandler(BaseHTTPRequestHandler):
    """Returns paginated results with Link headers."""

    page_counter = 0

    def log_message(self, *args):
        pass
    def do_GET(self):
        _LinkPaginationHandler.page_counter += 1
        page = _LinkPaginationHandler.page_counter
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if page < 3:
            self.send_header("Link", f'<http://localhost:{self.server.server_address[1]}/page?page={page+1}>; rel="next"')
        self.end_headers()
        self.wfile.write(json.dumps([{"page": page, "id": page}]).encode())


# ── Helpers ─────────────────────────────────────────────────────────

def _make_ctx(
    http_client: httpx.AsyncClient | None = None,
    credentials: dict[str, Any] | None = None,
    env_vars: dict[str, str] | None = None,
) -> NodeContext:
    return NodeContext(
        execution_id="test_exec",
        workflow_id="test_wf",
        node_id="http",
        logger=logging.getLogger("test_http"),
        http_client=http_client or httpx.AsyncClient(),
        storage=MemoryKVStore(),
        emit_event=lambda *a, **k: None,
        credentials=credentials or {},
        env_vars=env_vars or {},
        user_id=1,
    )


def _start_server(handler_cls, port=0) -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", port), handler_cls)
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, actual_port


def _url(port: int, path: str = "/") -> str:
    return f"http://127.0.0.1:{port}{path}"


def _make_params(**overrides) -> HTTPRequestParams:
    defaults = {"url": "http://127.0.0.1:1/test"}
    defaults.update(overrides)
    return HTTPRequestParams(**defaults)


# ══════════════════════════════════════════════════════════════════════
#  HTTP REQUEST NODE TESTS
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_01_get_with_query_and_headers():
    """Test 1: GET request with query params and headers."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(
            method="GET", url=_url(port),
            sendQuery=True, query={"foo": "bar", "baz": "42"},
            sendHeaders=True, headers={"X-Custom": "test-val"},
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        item = result.output_items[0]
        assert item["status"] == 200
        # Mock handler echoes request details — response data at top level
        assert item["method"] == "GET"
        assert "foo=bar" in item["path"]
        # Request headers are in the request metadata (response body's "headers" collides with HTTP response headers)
        sent_headers = item["request"]["headers"]
        assert any(k.lower() == "x-custom" and v == "test-val" for k, v in sent_headers.items())
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_02_post_json_body():
    """Test 2: POST request with JSON body."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(
            method="POST", url=_url(port),
            sendBody=True, body={"name": "Alice", "age": 30},
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        item = result.output_items[0]
        assert item["status"] == 201
        # Mock handler echoes request details — response data at top level
        assert item["method"] == "POST"
        assert item["body"]["name"] == "Alice"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_03_patch_request():
    """Test 3: PATCH request with JSON body."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(
            method="PATCH", url=_url(port),
            sendBody=True, body={"status": "updated"},
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        item = result.output_items[0]
        assert item["status"] == 200
        # Mock handler echoes request details — response data at top level
        assert item["method"] == "PATCH"
        assert item["body"]["status"] == "updated"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_04_delete_request():
    """Test 4: DELETE request."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(method="DELETE", url=_url(port))
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        item = result.output_items[0]
        assert item["status"] == 200
        assert item["method"] == "DELETE"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_05_post_form_urlencoded():
    """Test 5: POST with form-urlencoded body."""
    server, port = _start_server(_FormEchoHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(
            method="POST", url=_url(port),
            sendBody=True,
            body={"field1": "value1", "field2": "value2"},
            body_format="form",
            bodyContentType="form-urlencoded",
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        item = result.output_items[0]
        assert item["status"] == 201
        # FormEchoHandler returns {content_type, body} — now at top level
        assert "form-urlencoded" in item["content_type"]
        assert "field1=value1" in item["body"]
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_06_post_multipart_body():
    """Test 6: POST with multipart body (uses file dict to trigger multipart encoding)."""
    server, port = _start_server(_FormEchoHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(
            method="POST", url=_url(port),
            sendBody=True,
            body={"file": {"filename": "test.txt", "content": "hello", "contentType": "text/plain"}},
            body_format="multipart",
            bodyContentType="multipart-form-data",
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        item = result.output_items[0]
        assert item["status"] == 201
        assert "multipart" in item["content_type"]
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_07_timeout_behavior():
    """Test 7: Timeout triggers HTTP_TIMEOUT error."""
    server, port = _start_server(_TimeoutHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(
            method="GET", url=_url(port),
            timeout_seconds=1.0,
        )
        node = HTTPRequestNode()
        with pytest.raises(NodeExecutionError) as exc_info:
            await node.run(ctx, params, [{}])
        assert exc_info.value.code == "HTTP_TIMEOUT"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_08_http_error_4xx():
    """Test 8: HTTP 4xx raises NodeExecutionError with HTTP_4xx code."""
    server, port = _start_server(_Error4xxHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(method="GET", url=_url(port))
        node = HTTPRequestNode()
        with pytest.raises(NodeExecutionError) as exc_info:
            await node.run(ctx, params, [{}])
        assert "422" in exc_info.value.message
        assert exc_info.value.code == "HTTP_422"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_09_http_error_5xx():
    """Test 9: HTTP 5xx raises NodeExecutionError with retryable flag."""
    server, port = _start_server(_Error5xxHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(method="GET", url=_url(port))
        node = HTTPRequestNode()
        with pytest.raises(NodeExecutionError) as exc_info:
            await node.run(ctx, params, [{}])
        assert "503" in exc_info.value.message
        assert exc_info.value.code == "HTTP_503"
        assert exc_info.value.retryable is True
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_10_response_parsing_json_auto():
    """Test 10a: Response auto-detect JSON from content-type."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(method="GET", url=_url(port), response_format="auto")
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        assert isinstance(result.output_items[0], dict)
        assert "status" in result.output_items[0]
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_11_response_parsing_text():
    """Test 10b: Response forced to text."""
    server, port = _start_server(_TextHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(method="GET", url=_url(port), response_format="text")
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        assert result.output_items[0]["body"] == "hello plain text"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_12_expression_resolution_in_url():
    """Test 11: Expression resolution in URL path."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        item = {"path": "users"}
        params = HTTPRequestParams(
            method="GET",
            url=f"http://127.0.0.1:{port}/api/{{{{ $json.path }}}}",
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [item])
        assert "/api/users" in result.output_items[0]["path"]
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_13_expression_resolution_in_headers():
    """Test 12: Expression resolution in Authorization header."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        item = {"token": "my-secret-token"}
        params = HTTPRequestParams(
            method="GET", url=_url(port),
            sendHeaders=True,
            headers={"Authorization": "Bearer {{ $json.token }}"},
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [item])
        # The echoed request headers from mock are filtered out (collides with HTTP response headers)
        # Check that the Authorization header was sent via request metadata (redacted)
        sent = result.output_items[0]["request"]["headers"]
        assert any("authorization" in k.lower() and "REDACTED" in v for k, v in sent.items())
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_14_expression_resolution_in_body():
    """Test 13: Expression resolution in JSON body."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        item = {"name": "Bob", "role": "admin"}
        params = HTTPRequestParams(
            method="POST", url=_url(port),
            sendBody=True,
            body={"user": "{{ $json.name }}", "role": "{{ $json.role }}"},
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [item])
        # Mock handler echoes request body in response's "body" field
        # Response data is at top level
        echoed_body = result.output_items[0]["body"]
        assert echoed_body["user"] == "Bob"
        assert echoed_body["role"] == "admin"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_15_per_item_resolution():
    """Test 14: Per-item resolution with 3 items hitting different URLs."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        items = [
            {"path": "alpha"},
            {"path": "beta"},
            {"path": "gamma"},
        ]
        params = HTTPRequestParams(
            method="GET",
            url=f"http://127.0.0.1:{port}/api/{{{{ $json.path }}}}",
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, items)
        assert len(result.output_items) == 3
        paths = [item["path"] for item in result.output_items]
        assert "/api/alpha" in paths
        assert "/api/beta" in paths
        assert "/api/gamma" in paths
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_16_ssrf_blocks_private_ip_in_production():
    """Test 15: SSRF blocks 127.0.0.1 in production mode."""
    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(app_env="production")
        ctx = _make_ctx()
        params = HTTPRequestParams(method="GET", url="http://127.0.0.1:8080/secret")
        node = HTTPRequestNode()
        with pytest.raises(NodeExecutionError) as exc_info:
            await node.run(ctx, params, [{}])
        assert exc_info.value.code == "SSRF_BLOCKED"


@pytest.mark.asyncio
async def test_17_large_response_handling():
    """Test 16: Large (~1MB) response is handled."""
    server, port = _start_server(_LargeResponseHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(
            method="GET", url=_url(port),
            max_response_bytes=2 * 1024 * 1024,
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        assert result.output_items[0]["status"] == 200
        assert isinstance(result.output_items[0], dict)
        assert "data" in result.output_items[0]
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_18_curl_import_parsing():
    """Test 17: cURL import parsing."""
    curl_str = (
        'curl -X POST https://api.example.com/data '
        '-H "Content-Type: application/json" '
        '-H "Authorization: Bearer tok123" '
        '-d \'{"key": "value"}\''
    )
    result = parse_curl(curl_str)
    assert result["method"] == "POST"
    assert result["url"] == "https://api.example.com/data"
    assert result["headers"]["Content-Type"] == "application/json"
    assert result["auth_type"] == "bearer"
    assert result["auth_token"] == "tok123"
    assert result["body"] == {"key": "value"}


@pytest.mark.asyncio
async def test_19_curl_basic_auth():
    """Test 18a: cURL with -u basic auth."""
    curl_str = 'curl -u user:pass https://api.example.com/secure'
    result = parse_curl(curl_str)
    assert result["auth_type"] == "basic"
    assert result["auth_username"] == "user"
    assert result["auth_password"] == "pass"


@pytest.mark.asyncio
async def test_20_curl_bearer_auth():
    """Test 18b: cURL with Authorization: Bearer header."""
    curl_str = 'curl -H "Authorization: Bearer mytoken" https://api.example.com/'
    result = parse_curl(curl_str)
    assert result["auth_type"] == "bearer"
    assert result["auth_token"] == "mytoken"


@pytest.mark.asyncio
async def test_21_bearer_auth_inline():
    """Test 19: Bearer auth via inline auth_type."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(
            method="GET", url=_url(port),
            auth_type="bearer", auth_token="tok_bearer_123",
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        sent = result.output_items[0]["request"]["headers"]
        assert any("authorization" in k.lower() and "REDACTED" in v for k, v in sent.items())
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_22_basic_auth_inline():
    """Test 20: Basic auth via inline auth_type."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(
            method="GET", url=_url(port),
            auth_type="basic", auth_username="admin", auth_password="secret",
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        sent = result.output_items[0]["request"]["headers"]
        assert any("authorization" in k.lower() and "REDACTED" in v for k, v in sent.items())
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_23_api_key_in_header():
    """Test 21: API key sent as header."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(
            method="GET", url=_url(port),
            auth_type="api_key",
            auth_token="apikey_xyz",
            api_key_name="X-API-Key",
            api_key_in="header",
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        sent = result.output_items[0]["request"]["headers"]
        assert any("x-api-key" in k.lower() and "REDACTED" in v for k, v in sent.items())
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_24_api_key_in_query():
    """Test 22: API key sent as query parameter."""
    server, port = _start_server(_MockHandler)
    try:
        ctx = _make_ctx()
        params = HTTPRequestParams(
            method="GET", url=_url(port),
            auth_type="api_key",
            auth_token="apikey_query",
            api_key_name="api_key",
            api_key_in="query",
        )
        node = HTTPRequestNode()
        result = await node.run(ctx, params, [{}])
        path = result.output_items[0]["path"]
        assert "api_key=apikey_query" in path
    finally:
        server.shutdown()


# ══════════════════════════════════════════════════════════════════════
#  CREDENTIAL SYSTEM TESTS
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_25_credential_encryption_decryption_roundtrip():
    """Test 23: Credential encryption/decryption produces identical plaintext."""
    from app.security.crypto import encrypt_text, decrypt_text

    plaintext = json.dumps({"api_key": "sk-12345", "password": "p@ss!"})
    encrypted = encrypt_text(plaintext)
    assert encrypted != plaintext.encode()
    decrypted = decrypt_text(encrypted)
    assert json.loads(decrypted) == {"api_key": "sk-12345", "password": "p@ss!"}


@pytest.mark.asyncio
async def test_26_credential_resolution_from_db():
    """Test 24: CredentialResolver resolves from DB (mocked store)."""
    from app.credentials.resolver import CredentialResolver
    from app.credentials.service import CredentialError
    from unittest.mock import MagicMock, patch

    mock_rec = MagicMock()
    mock_rec.type = "basic_auth"
    mock_rec.name = "My Basic Auth"
    mock_rec.data = b"k0:fake-encrypted-data"

    mock_store = MagicMock()
    mock_store.get_encrypted.return_value = mock_rec
    mock_store.decrypt.return_value = {"username": "admin", "password": "secret"}

    resolver = CredentialResolver()
    with patch("app.credentials.resolver.get_credential_store", return_value=mock_store):
        with patch("app.credentials.resolver.get_credential_type_registry") as mock_tr:
            mock_tr.return_value.get.return_value = {
                "provider": "basic", "implemented": True
            }
            with patch("app.credentials.resolver.get_provider_registry") as mock_pr:
                mock_prov = MagicMock()
                mock_prov.validateCredential = MagicMock()
                mock_pr.return_value.get.return_value = mock_prov
                data, provider = resolver.resolve(
                    MagicMock(), 1, "basic_auth", "cred_test"
                )
                assert data["username"] == "admin"
                assert data["password"] == "secret"
                mock_prov.validateCredential.assert_called_once_with(data)


@pytest.mark.asyncio
async def test_27_missing_credential_error():
    """Test 25: Missing credential ID raises CredentialError."""
    from app.credentials.resolver import CredentialResolver
    from app.credentials.service import CredentialError

    resolver = CredentialResolver()
    with pytest.raises(CredentialError) as exc_info:
        resolver.resolve(MagicMock(), 1, "basic_auth", "")
    assert "Missing credentialId" in str(exc_info.value)


@pytest.mark.asyncio
async def test_28_invalid_credential_type_error():
    """Test 26: Unknown credential type raises ValueError."""
    from app.credentials.resolver import CredentialResolver
    from unittest.mock import MagicMock, patch

    resolver = CredentialResolver()
    with patch("app.credentials.resolver.get_credential_type_registry") as mock_tr:
        mock_tr.return_value.get.return_value = None
        with patch("app.credentials.registry.is_known_type", return_value=False):
            with pytest.raises(ValueError) as exc_info:
                resolver.resolve(MagicMock(), 1, "nonexistent_type", "cred_x")
            assert "Unknown credential type" in str(exc_info.value)


# ══════════════════════════════════════════════════════════════════════
#  EXPRESSION ENGINE TESTS (supplementary)
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_29_expression_dollar_json_resolution():
    """Expression engine resolves $json.field correctly."""
    ctx = {"$json": {"name": "Alice", "age": 30}}
    assert expressions.resolve("{{ $json.name }}", ctx) == "Alice"
    assert expressions.resolve("{{ $json.age }}", ctx) == 30


@pytest.mark.asyncio
async def test_30_expression_nested_path():
    """Expression engine resolves nested dot paths."""
    ctx = {"$json": {"user": {"address": {"city": "NYC"}}}}
    assert expressions.resolve("{{ $json.user.address.city }}", ctx) == "NYC"


@pytest.mark.asyncio
async def test_31_expression_array_index():
    """Expression engine resolves array indexing."""
    ctx = {"$json": {"items": ["a", "b", "c"]}}
    assert expressions.resolve("{{ $json.items[1] }}", ctx) == "b"


@pytest.mark.asyncio
async def test_32_expression_pipe_upper():
    """Expression engine applies pipe | upper."""
    ctx = {"$json": {"name": "alice"}}
    assert expressions.resolve("{{ $json.name | upper }}", ctx) == "ALICE"


@pytest.mark.asyncio
async def test_33_expression_arithmetic():
    """Expression engine performs arithmetic."""
    ctx = {"$json": {"a": 5, "b": 3}}
    assert expressions.resolve("{{ $json.a + $json.b }}", ctx) == 8
    assert expressions.resolve("{{ $json.a * $json.b }}", ctx) == 15


@pytest.mark.asyncio
async def test_34_expression_coalesce():
    """Expression engine handles ?? coalesce."""
    ctx = {"$json": {"existing": "yes"}}
    assert expressions.resolve("{{ $json.missing ?? 'default' }}", ctx) == "default"
    assert expressions.resolve("{{ $json.existing ?? 'default' }}", ctx) == "yes"
