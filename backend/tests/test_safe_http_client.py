"""SafeHTTPClient regression tests.

Regression: a real Salesforce run (Phase 13) failed with
"httpx.Timeout must either include a default, or set all four parameters
explicitly" — the real AsyncClient was never constructed under test, so
the broken `httpx.Timeout(connect=..., read=..., pool=...)` (missing
`write`) went unnoticed. These tests construct the real client.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.security.safe_http_client import SafeHTTPClient


@pytest.mark.asyncio
async def test_real_async_client_construction_succeeds() -> None:
    """The real httpx.AsyncClient must build with the configured timeouts
    (httpx 0.28+ keyword form needs connect/read/write/pool)."""
    client = SafeHTTPClient(timeout_s=5.0)
    try:
        await client._ensure_client()
        assert client._client is not None
        timeout = client._client.timeout
        assert timeout.connect == 5.0
        assert timeout.read == 5.0
        assert timeout.write == 5.0
        assert timeout.pool == 5.0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_context_manager_constructs_and_requests() -> None:
    """__aenter__ builds the real client; a request via the inner client
    is dispatched (inner mocked to avoid network). The default response
    size cap routes through the streaming path."""

    class _StreamCM:
        def __init__(self, response: httpx.Response) -> None:
            self.response = response

        async def __aenter__(self) -> httpx.Response:
            return self.response

        async def __aexit__(self, *exc_info) -> None:
            return None

    fake_response = httpx.Response(200, json={"ok": True}, request=httpx.Request("GET", "http://fake"))
    fake_client = MagicMock()
    fake_client.stream = MagicMock(return_value=_StreamCM(fake_response))
    fake_client.aclose = AsyncMock(return_value=None)
    with patch.object(SafeHTTPClient, "_ensure_client", new=AsyncMock(return_value=fake_client)):
        async with SafeHTTPClient(timeout_s=5.0) as client:
            client._client = fake_client  # simulate successful construction
            response = await client.request("GET", "https://example.com/items")
    assert response.json() == {"ok": True}
    fake_client.stream.assert_called_once()
    # __aexit__ intentionally does NOT close the pool (shared across requests)


@pytest.mark.asyncio
async def test_custom_timeout_parts_build() -> None:
    """Partial overrides still yield a valid all-four Timeout."""
    client = SafeHTTPClient(timeout_s=10.0, connect_timeout_s=2.0, read_timeout_s=60.0)
    try:
        await client._ensure_client()
        assert client._client is not None
        timeout = client._client.timeout
        assert timeout.connect == 2.0
        assert timeout.read == 60.0
        assert timeout.write == 60.0
        assert timeout.pool == 60.0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_decoding_error_retries_with_identity_encoding() -> None:
    """A malformed gzip body (Salesforce/F5 quirk) must be retried once
    with Accept-Encoding: identity instead of surfacing a raw
    decompression failure."""
    calls: list[dict] = []

    class _StreamCM:
        def __init__(self, response: httpx.Response) -> None:
            self.response = response

        async def __aenter__(self) -> httpx.Response:
            return self.response

        async def __aexit__(self, *exc_info) -> None:
            return None

    def _stream(method, url, **kwargs):
        calls.append(kwargs)
        if kwargs.get("headers", {}).get("Accept-Encoding") == "identity":
            body = b'{"decoded": true}'
            headers = {"Content-Type": "application/json"}
        else:
            body = b'{"broken": true}'
            headers = {"Content-Type": "application/json", "Content-Encoding": "gzip"}
        return _StreamCM(
            httpx.Response(200, content=body, headers=headers, request=httpx.Request(method, url))
        )

    fake_client = MagicMock()
    fake_client.stream = _stream
    fake_client.aclose = AsyncMock(return_value=None)
    with patch.object(SafeHTTPClient, "_ensure_client", new=AsyncMock(return_value=fake_client)):
        async with SafeHTTPClient(timeout_s=5.0) as client:
            client._client = fake_client
            response = await client.get("https://example.com/token")

    assert response.json() == {"decoded": True}
    assert calls[1]["headers"]["Accept-Encoding"] == "identity"


@pytest.mark.asyncio
async def test_decoding_error_identity_fails_once_and_raises() -> None:
    """When the identity retry still fails to decode, a single clear
    ConnectorError is raised — no infinite recursion."""
    calls: list[dict] = []

    class _StreamCM:
        def __init__(self, response: httpx.Response) -> None:
            self.response = response

        async def __aenter__(self) -> httpx.Response:
            return self.response

        async def __aexit__(self, *exc_info) -> None:
            return None

    def _stream(method, url, **kwargs):
        calls.append(kwargs)
        return _StreamCM(
            httpx.Response(
                200,
                content=b"garbage",
                headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
                request=httpx.Request(method, url),
            )
        )

    fake_client = MagicMock()
    fake_client.stream = _stream
    fake_client.aclose = AsyncMock(return_value=None)
    with patch.object(SafeHTTPClient, "_ensure_client", new=AsyncMock(return_value=fake_client)):
        async with SafeHTTPClient(timeout_s=5.0) as client:
            client._client = fake_client
            with pytest.raises(Exception) as exc_info:
                await client.get("https://example.com/token")

    assert len(calls) == 2
    assert calls[1]["headers"]["Accept-Encoding"] == "identity"
    assert "could not be decoded" in str(exc_info.value)