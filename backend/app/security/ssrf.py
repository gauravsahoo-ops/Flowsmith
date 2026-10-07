"""Shared outbound-URL guard for node egress (S10: SSRF protection).

Reuses SafeHTTPClient's host/IP primitives so connector validation and
node HTTP calls enforce one policy, and adds DNS resolution: a public
hostname that resolves to an internal address is rejected too.

Dev keeps the historical loopback allowance (local stubs/test servers);
the SAFE_HTTP_ALLOWED_HOSTS escape hatch bypasses the policy for exact
hosts in any environment.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from app.engine.errors import NodeExecutionError
from app.security.safe_http_client import (
    _env_allowed_hosts,
    _ipv4_blocked,
    _ipv6_blocked,
    _is_blocked_host,
    _parse_literal_ip,
)

_DNS_TIMEOUT_S = 5.0

_LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})

_AnyIP = ipaddress.IPv4Address | ipaddress.IPv6Address


def _ip_restricted(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv4Address):
        return _ipv4_blocked(ip)
    if isinstance(ip, ipaddress.IPv6Address):
        return _ipv6_blocked(ip)
    return True  # unknown address family: fail closed


async def _resolve_ips(host: str) -> list[_AnyIP]:
    """Resolve *host*; returns [] on timeout/failure (request will fail itself)."""
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, None, type=socket.SOCK_STREAM),
            timeout=_DNS_TIMEOUT_S,
        )
    except (asyncio.TimeoutError, OSError, socket.gaierror):
        return []
    resolved: list[_AnyIP] = []
    for info in infos:
        try:
            resolved.append(ipaddress.ip_address(str(info[4][0]).split("%")[0]))
        except ValueError:
            continue
    return resolved


async def assert_public_url(url: str, *, node_id: str, code: str = "SSRF_BLOCKED") -> None:
    """Raise NodeExecutionError (retryable=False) when *url* targets an internal address.

    Checks, in order: http(s) scheme, exact-host env allowlist, dev
    loopback exemption, literal-IP / internal-hostname policy, then DNS
    resolution (every resolved address must be public; dev may resolve
    to loopback).
    """
    def _deny(message: str) -> NodeExecutionError:
        return NodeExecutionError(message, code=code, node_id=node_id, retryable=False)

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise _deny(f"SSRF blocked: scheme '{parsed.scheme or '(none)'}' is not allowed.")
    host = (parsed.hostname or "").strip("[]")
    if not host:
        raise _deny("SSRF blocked: URL has no host.")

    allowed = _env_allowed_hosts()
    if allowed and host.lower() in allowed:
        return

    from app.config import get_settings

    try:
        dev = get_settings().app_env != "production"
    except Exception:  # pragma: no cover - settings failure defaults safe
        dev = False

    if dev and host.lower() in _LOOPBACK_NAMES:
        return

    literal = _parse_literal_ip(host)
    if literal is not None and _ip_restricted(literal):
        raise _deny(f"SSRF blocked: '{host}' is a private/internal address.")
    if _is_blocked_host(host):
        raise _deny(f"SSRF blocked: '{host}' is not allowed.")

    for ip in await _resolve_ips(host):
        if not _ip_restricted(ip):
            continue
        if dev and ip.is_loopback:
            continue
        raise _deny(f"SSRF blocked: '{host}' resolves to internal address '{ip}'.")
