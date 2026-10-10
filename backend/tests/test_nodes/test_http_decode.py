"""Lenient response decoding for the HTTP-family nodes.

Salesforce's F5 edge (and similar proxies) advertises ``Content-Encoding:
gzip`` over a body it never compressed; httpx then fails with
``Error -3 while decompressing data: incorrect header check``. The
connector layer (SafeHTTPClient) already recovers by replaying with
``Accept-Encoding: identity``; these tests pin the same guarantees for the
plain-AsyncClient path used by the HTTP Request node (request_with_size_cap
/ _stream_capped).

Mock responses are built with ``stream=httpx.ByteStream(...)`` (like a real
transport) because ``httpx.Response(content=...)`` pre-reads and decodes at
construction time — which would swallow the very failure under test.
"""

from __future__ import annotations

import gzip
import zlib

import httpx
import pytest

from app.engine.errors import NodeExecutionError
from app.engine.node_base import request_with_size_cap


def _gzip(data: bytes) -> bytes:
    return gzip.compress(data)


def _raw_deflate(data: bytes) -> bytes:
    obj = zlib.compressobj(wbits=-15)
    return obj.compress(data) + obj.flush()


def _resp(body: bytes, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(200, headers=headers or {}, stream=httpx.ByteStream(body))


@pytest.mark.asyncio
async def test_header_lie_gzip_over_plain_body_returns_plain() -> None:
    """Content-Encoding: gzip + plain body (the F5 quirk) must yield the
    body as-is instead of raising a decompression error."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _resp(
            b'{"ok": true}',
            {"Content-Type": "application/json", "Content-Encoding": "gzip"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await request_with_size_cap(
            client, "GET", "https://example.com/api", max_response_bytes=None,
            node_id="http_request",
        )

    assert response.json() == {"ok": True}
    assert len(calls) == 1  # recovered in-process, no replay needed


@pytest.mark.asyncio
async def test_valid_gzip_body_still_decodes() -> None:
    payload = b'{"items": [1, 2, 3]}'

    def handler(request: httpx.Request) -> httpx.Response:
        return _resp(
            _gzip(payload),
            {"Content-Type": "application/json", "Content-Encoding": "gzip"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await request_with_size_cap(
            client, "GET", "https://example.com/api", max_response_bytes=None,
            node_id="http_request",
        )

    assert response.content == payload


@pytest.mark.asyncio
async def test_raw_deflate_body_with_deflate_header_decodes() -> None:
    """RFC-violating servers send raw DEFLATE (no zlib wrapper) behind
    Content-Encoding: deflate; both framings must decode."""
    payload = b'{"ok": true}'

    def handler(request: httpx.Request) -> httpx.Response:
        return _resp(
            _raw_deflate(payload),
            {"Content-Type": "application/json", "Content-Encoding": "deflate"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await request_with_size_cap(
            client, "GET", "https://example.com/api", max_response_bytes=None,
            node_id="http_request",
        )

    assert response.content == payload


@pytest.mark.asyncio
async def test_corrupt_gzip_get_replays_with_identity() -> None:
    """A body that really carries the gzip framing but is corrupt is
    replayed once with Accept-Encoding: identity (safe for GET)."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if (request.headers.get("Accept-Encoding") or "").lower() == "identity":
            return _resp(b'{"recovered": true}', {"Content-Type": "application/json"})
        return _resp(
            b"\x1f\x8b" + b"garbage-not-a-gzip-stream",
            {"Content-Type": "application/json", "Content-Encoding": "gzip"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await request_with_size_cap(
            client, "GET", "https://example.com/api", max_response_bytes=None,
            node_id="http_request",
        )

    assert response.json() == {"recovered": True}
    assert len(calls) == 2
    assert (calls[1].headers.get("Accept-Encoding") or "").lower() == "identity"


@pytest.mark.asyncio
async def test_corrupt_gzip_get_identity_replay_still_fails_cleanly() -> None:
    """When identity also fails, a single clear (retryable) error surfaces
    — no raw zlib text, no infinite replay."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _resp(
            b"\x1f\x8b" + b"garbage",
            {"Content-Type": "application/json", "Content-Encoding": "gzip"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NodeExecutionError) as exc_info:
            await request_with_size_cap(
                client, "GET", "https://example.com/api", max_response_bytes=None,
                node_id="http_request",
            )

    assert "could not be decoded" in str(exc_info.value)
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_corrupt_gzip_post_fails_without_replay() -> None:
    """A POST must never be replayed automatically: the mutation may have
    already executed server-side."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _resp(
            b"\x1f\x8b" + b"garbage",
            {"Content-Type": "application/json", "Content-Encoding": "gzip"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NodeExecutionError) as exc_info:
            await request_with_size_cap(
                client, "POST", "https://example.com/api", max_response_bytes=None,
                node_id="http_request", json={"a": 1},
            )

    assert len(calls) == 1  # exactly one attempt — no duplicate mutation
    assert "could not be decoded" in str(exc_info.value)
    assert exc_info.value.retryable is False
    assert exc_info.value.code == "HTTP_REQUEST_FAILED"


@pytest.mark.asyncio
async def test_size_cap_still_enforced_on_plain_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _resp(b"x" * 64)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NodeExecutionError) as exc_info:
            await request_with_size_cap(
                client, "GET", "https://example.com/api", max_response_bytes=16,
                node_id="http_request",
            )

    assert exc_info.value.code == "RESPONSE_TOO_LARGE"


@pytest.mark.asyncio
async def test_gzip_bomb_output_bounded_by_cap() -> None:
    """A tiny compressed body that expands past the cap must fail — the
    bound applies to the DECODED size, not the compressed size."""
    big = b"A" * 4096

    def handler(request: httpx.Request) -> httpx.Response:
        return _resp(
            _gzip(big),
            {"Content-Type": "application/json", "Content-Encoding": "gzip"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NodeExecutionError) as exc_info:
            await request_with_size_cap(
                client, "GET", "https://example.com/api", max_response_bytes=1024,
                node_id="http_request",
            )

    assert exc_info.value.code == "RESPONSE_TOO_LARGE"
