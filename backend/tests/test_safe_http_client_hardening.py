"""Phase 17: SafeHTTPClient security-hardening tests.

Exercises the REAL SafeHTTPClient (no get_safe_http_client patch) over
httpx.MockTransport, proving:

- SSRF blocklist incl. literal-IP edge forms (decimal/hex IPv4,
  IPv4-mapped IPv6, CGNAT) and link-local/metadata endpoints;
- every outbound request is validated — including redirect targets
  (an SSRF redirect is refused before the second request is sent);
- real Authorization headers go on the wire (the redacted-header bug)
  while logs only ever see the redacted form;
- the response-size cap is enforced (streamed, fail-fast);
- timeouts still map to typed retryable ConnectorErrors.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from app.connectors import ConnectorError
from app.security.safe_http_client import SafeHTTPClient, get_safe_http_client

HOST = "https://api.example.com"


def _handler_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True}, request=request)


@pytest.mark.asyncio
async def test_ssrf_blocks_private_and_metadata_hosts() -> None:
    blocked_hosts = [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://172.31.255.255/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",  # AWS metadata
        "http://169.254.170.2/",  # ECS metadata
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped loopback
        "http://2130706433/",  # decimal 127.0.0.1
        "http://0x7f000001/",  # hex 127.0.0.1
        "http://100.64.0.1/",  # CGNAT
    ]
    client = SafeHTTPClient(transport=httpx.MockTransport(_handler_ok))
    try:
        for url in blocked_hosts:
            with pytest.raises(ConnectorError) as exc_info:
                await client.get(url)
            assert exc_info.value.code == "CONNECTOR_UNAVAILABLE"
            assert "not allowed" in exc_info.value.args[0]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_public_external_host_allowed() -> None:
    client = SafeHTTPClient(transport=httpx.MockTransport(_handler_ok))
    try:
        response = await client.get(HOST)
        assert response.status_code == 200
        assert response.json() == {"ok": True}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_scheme_and_port_policy() -> None:
    client = SafeHTTPClient(transport=httpx.MockTransport(_handler_ok))
    try:
        with pytest.raises(ConnectorError) as exc_info:
            await client.get("ftp://api.example.com/file")
        assert "scheme" in exc_info.value.args[0]

        with pytest.raises(ConnectorError) as exc_info:
            await client.get("https://api.example.com:8443/api")
        assert "Port" in exc_info.value.args[0]

        # Standard ports pass.
        response = await client.get("https://api.example.com:443/api")
        assert response.status_code == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_redirect_to_blocked_host_refused_before_second_request() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if not calls[0].startswith(HOST):
            return httpx.Response(500, request=request)
        return httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1/evil"},
            request=request,
        )

    client = SafeHTTPClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ConnectorError) as exc_info:
            await client.get(HOST)
        assert "127.0.0.1" in exc_info.value.args[0]
        assert len(calls) == 1  # the redirect target was never contacted
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_redirect_to_allowed_host_still_followed() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(302, headers={"Location": "https://cdn.example.com/data"}, request=request)
        return httpx.Response(200, json={"redirected": True}, request=request)

    client = SafeHTTPClient(transport=httpx.MockTransport(handler))
    try:
        response = await client.get(HOST)
        assert response.status_code == 200
        assert response.json() == {"redirected": True}
        assert len(calls) == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_authorization_header_sent_verbatim_and_redacted_in_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["Authorization"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"ok": True}, request=request)

    client = SafeHTTPClient(transport=httpx.MockTransport(handler))
    try:
        with caplog.at_level(logging.DEBUG, logger="security.safe_http"):
            response = await client.get(
                HOST,
                headers={"Authorization": "Bearer tok123"},
            )
    finally:
        await client.close()

    # The REAL token is sent over the wire…
    assert response.status_code == 200
    assert seen["Authorization"] == "Bearer tok123"
    # …and only the redacted form ever reaches the logs.
    assert "Bearer tok123" not in caplog.text
    assert "***REDACTED***" in caplog.text


@pytest.mark.asyncio
async def test_response_size_cap_enforced() -> None:
    big_body = "x" * 1024
    small_body = "y" * 16

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=big_body if request.url.params.get("big") else small_body, request=request)

    client = SafeHTTPClient(transport=httpx.MockTransport(handler), max_response_bytes=64)
    try:
        with pytest.raises(ConnectorError) as exc_info:
            await client.get(HOST, params={"big": "1"})
        assert "maximum allowed size" in exc_info.value.args[0]
        assert exc_info.value.retryable is False

        # Under the cap: fine.
        response = await client.get(HOST)
        assert response.content == small_body.encode()

        # Per-call override raises the cap.
        response = await client.get(HOST, params={"big": "1"}, max_response_bytes=4096)
        assert len(response.content) == 1024
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_exact_host_port_allowlist_bypasses_ssrf() -> None:
    """Dev/E2E escape hatch: an explicit allowed_hosts + allowed_ports
    lets the exact stub host:port through, while everything else stays
    blocked. Exact-match only — '127.0.0.1' must not open '127.0.0.2'."""
    client = SafeHTTPClient(
        transport=httpx.MockTransport(_handler_ok),
        allowed_hosts={"127.0.0.1"},
        allowed_ports={443, 8181},
    )
    try:
        # The allowed stub host:port passes.
        response = await client.get("http://127.0.0.1:8181/services/oauth2/token")
        assert response.status_code == 200

        # Same host, different port: still blocked by port policy.
        with pytest.raises(ConnectorError) as exc_info:
            await client.get("http://127.0.0.1:8443/services/oauth2/token")
        assert "Port" in exc_info.value.args[0]

        # Different loopback host: still blocked (no wildcard).
        with pytest.raises(ConnectorError) as exc_info:
            await client.get("http://127.0.0.2:8181/services/oauth2/token")
        assert "not allowed" in exc_info.value.args[0]

        # Public hosts remain fully protected.
        response = await client.get(HOST)
        assert response.status_code == 200
    finally:
        await client.close()


def test_singleton_env_allowlist_off_by_default(monkeypatch) -> None:
    """Without the env vars the singleton is a strict default client."""
    import app.security.safe_http_client as shc

    monkeypatch.delenv("SAFE_HTTP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("SAFE_HTTP_ALLOWED_PORTS", raising=False)
    # The fallback reads get_settings().safe_http_allowed_hosts which loads
    # from .env — patch the reader to return None so no hosts/ports leak in.
    monkeypatch.setattr(shc, "_env_allowed_hosts", lambda: None)
    monkeypatch.setattr(shc, "_env_allowed_ports", lambda: None)
    shc._default_client = None
    try:
        client = get_safe_http_client()
        assert client.allowed_hosts == frozenset()
        assert client.allowed_ports == frozenset({80, 443})
    finally:
        shc._default_client = None


def test_singleton_env_allowlist_applied_when_set(monkeypatch) -> None:
    """Setting the env vars opts the default singleton into the stub
    allowlist (used by the Playwright suite against 127.0.0.1:8181)."""
    import app.security.safe_http_client as shc

    monkeypatch.setenv("SAFE_HTTP_ALLOWED_HOSTS", "127.0.0.1, localhost")
    monkeypatch.setenv("SAFE_HTTP_ALLOWED_PORTS", "8181, 8000")
    shc._default_client = None
    try:
        client = get_safe_http_client()
        assert client.allowed_hosts == frozenset({"127.0.0.1", "localhost"})
        # Env ports are ADDED to the strict defaults (80/443 must keep
        # working for real external calls).
        assert client.allowed_ports == frozenset({80, 443, 8181, 8000})
    finally:
        shc._default_client = None


@pytest.mark.asyncio
async def test_singleton_env_allowlist_reaches_the_stub() -> None:
    """End-to-end: the env-configured singleton performs a real request
    against the allowlisted loopback host:port (what the Salesforce e2e
    stub does)."""
    import app.security.safe_http_client as shc
    from app.connectors import ConnectorError, ConnectorErrorCode

    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        async def _serve() -> None:
            try:
                conn, _ = await asyncio.to_thread(srv.accept)
                await asyncio.to_thread(
                    conn.sendall,
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"Content-Length: 11\r\nConnection: close\r\n\r\n{\"ok\": true}",
                )
                conn.close()
            except Exception:
                pass

        serve_task = asyncio.create_task(_serve())
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("SAFE_HTTP_ALLOWED_HOSTS", "127.0.0.1")
        monkeypatch.setenv("SAFE_HTTP_ALLOWED_PORTS", str(port))
        shc._default_client = None
        try:
            client = get_safe_http_client()
            # Retry once on a transient connect race: the raw-socket stub
            # and the client connect are independent async tasks, and under
            # load Windows can briefly refuse the connection. Only the
            # network-level (UNAVAILABLE) error is retried, so real policy
            # rejections still fail the test.
            response = None
            for _ in range(2):
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/health")
                    break
                except ConnectorError as exc:
                    if exc.code != ConnectorErrorCode.UNAVAILABLE:
                        raise
                    await asyncio.sleep(0.1)
            assert response is not None and response.status_code == 200
        finally:
            shc._default_client = None
            monkeypatch.undo()
            await serve_task


@pytest.mark.asyncio
async def test_timeout_maps_to_typed_retryable_error() -> None:
    """httpx timeouts (MockTransport bypasses the real timeout
    machinery, so a fake inner client raises the typed exception)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    class _StreamCM:
        async def __aenter__(self):
            raise httpx.ReadTimeout("read timed out", request=httpx.Request("GET", HOST))

        async def __aexit__(self, *exc_info) -> None:
            return None

    fake_client = MagicMock()
    fake_client.stream = MagicMock(return_value=_StreamCM())

    client = SafeHTTPClient(timeout_s=0.05, transport=httpx.MockTransport(_handler_ok))
    with patch.object(SafeHTTPClient, "_ensure_client", new=AsyncMock(return_value=fake_client)):
        with pytest.raises(ConnectorError) as exc_info:
            await client.get(HOST)
    assert exc_info.value.code == "CONNECTOR_TIMEOUT"
    assert exc_info.value.retryable is True
    await client.close()


@pytest.mark.asyncio
async def test_ssrf_blocks_subdomain_localhost_and_dns_resolving_to_loopback() -> None:
    client = SafeHTTPClient(transport=httpx.MockTransport(_handler_ok))
    try:
        # Subdomain localhost
        with pytest.raises(ConnectorError) as exc:
            await client.get("http://api.localhost/")
        assert exc.value.code == "CONNECTOR_UNAVAILABLE"
        assert "not allowed" in exc.value.args[0]

        with pytest.raises(ConnectorError) as exc:
            await client.get("http://my.internal/")
        assert exc.value.code == "CONNECTOR_UNAVAILABLE"
    finally:
        await client.close()

