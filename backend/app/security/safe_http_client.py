"""SafeHTTPClient (spec 37.28).

A shared HTTP client with SSRF protections, timeout controls, and safe
logging for all external connector integrations.

Never logs authorization headers, API keys, Bearer tokens, cookies,
or credential values. All connections are validated against SSRF
attempts (localhost, loopback, private IP, link-local, cloud
metadata endpoints).

Usage:

    from app.security.safe_http_client import SafeHTTPClient
    client = SafeHTTPClient()
    response = await client.get("https://api.example.com/endpoint", params={"key": value})
    result = await client.close()

All external HTTP connectors must use this client rather than creating
their own httpx.AsyncClient instances.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from pydantic import BaseModel, Field

from app.connectors import ConnectorErrorCode, make_connector_error

logger = logging.getLogger("security.safe_http")

DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_ALLOWED_PORTS = frozenset({80, 443})

# Dev/E2E escape hatch (OFF by default). When set, these env vars let the
# default singleton allow EXACT hosts / EXACT ports past the SSRF policy —
# used only by the Playwright suite to reach the local Salesforce stub
# (127.0.0.1:8181). They never apply to explicit SafeHTTPClient instances
# and must not be set in production.
ENV_ALLOWED_HOSTS = "SAFE_HTTP_ALLOWED_HOSTS"
ENV_ALLOWED_PORTS = "SAFE_HTTP_ALLOWED_PORTS"


def _env_allowed_hosts() -> frozenset[str] | None:
    raw = os.environ.get(ENV_ALLOWED_HOSTS, "").strip()
    if not raw:
        # Fallback: read from pydantic settings (which load .env). This
        # lets the Playwright suite reach the local Salesforce stub
        # (127.0.0.1:8181) without needing the var exported in the
        # process environment.
        try:
            from app.config import get_settings
            raw = (get_settings().safe_http_allowed_hosts or "").strip()
        except Exception:
            raw = ""
    if not raw:
        return None
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


def _env_allowed_ports() -> frozenset[int] | None:
    raw = os.environ.get(ENV_ALLOWED_PORTS, "").strip()
    if not raw:
        # Fallback: read from pydantic settings (which load .env). See
        # _env_allowed_hosts above for rationale.
        try:
            from app.config import get_settings
            raw = (get_settings().safe_http_allowed_ports or "").strip()
        except Exception:
            raw = ""
    if not raw:
        return None
    ports: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit():
            continue
        port = int(part)
        if 1 <= port <= 65535:
            ports.add(port)
    return frozenset(ports) if ports else None


# ----------------------------------------------------------------------
# SSRF Blocked Hosts / Patterns
# ----------------------------------------------------------------------


# localhost and loopback (literal IPs and hostname forms)
_LOOPBACK_PATTERNS = re.compile(
    r"^(localhost|ip6-localhost|ip6-loopback|127\.\d{1,3}\.\d{1,3}\.\d{1,3}|::1|fe80::[\d:a-f]{0,39}|"
    r"fc[\da-f]{4}|::ffff:0:0:/?|255\.255\.255\.255|0\.0\.0\.0)$",
    re.IGNORECASE,
)

# Private IP ranges (RFC 1918)
_PRIVATE_IP_PATTERNS = re.compile(
    r"^((10\.\d{1,3}\.\d{1,3}\.\d{1,3})|(172\.1[6-9]\.\d{1,3}\.\d{1,3})|"
    r"(172\.2[0-9]\.\d{1,3}\.\d{1,3})|(172\.3[0-1]\.\d{1,3}\.\d{1,3})|"
    r"(192\.168\.\d{1,3}\.\d{1,3}))$",
    re.IGNORECASE,
)

# Link-local (169.254.0.0/16, fe80::/10)
_LINKLOCAL_PATTERNS = re.compile(
    r"^(169\.254\.\d{1,3}\.\d{1,3}|fe80::[\d:a-f]{0,39})$",
    re.IGNORECASE,
)

# Cloud metadata endpoints
_CLOUD_METADATA_PATTERNS = re.compile(
    r"^(169\.254\.169\.254)|(169\.254\.170\.2)$",
    re.IGNORECASE,
)


def _parse_literal_ip(host: str) -> ipaddress._BaseAddress | None:
    """Parse a host string as a literal IP, including decimal and hex
    IPv4 forms (e.g. ``2130706433`` for 127.0.0.1) and IPv4-mapped IPv6.

    Returns None when the host is a hostname (or unparseable).
    """
    h = host.lower().strip()
    if not h:
        return None
    if h.isdigit():
        try:
            return ipaddress.IPv4Address(int(h))
        except ValueError:
            return None
    if h.startswith("0x"):
        try:
            return ipaddress.IPv4Address(int(h, 16))
        except ValueError:
            return None
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        return None


def _ipv4_blocked(addr: ipaddress.IPv4Address) -> bool:
    if (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
    ):
        return True
    # CGNAT (100.64.0.0/10): not covered by is_private before Python 3.13
    return addr in ipaddress.IPv4Network("100.64.0.0/10")


def _ipv6_blocked(addr: ipaddress.IPv6Address) -> bool:
    mapped = addr.ipv4_mapped
    if mapped is not None:
        return _ipv4_blocked(mapped)
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
    )


def _is_blocked_host(host: str) -> bool:
    """Check if a host should be blocked for SSRF prevention."""
    host_lower = host.lower().strip()

    addr = _parse_literal_ip(host_lower)
    if isinstance(addr, ipaddress.IPv4Address):
        return _ipv4_blocked(addr)
    if isinstance(addr, ipaddress.IPv6Address):
        return _ipv6_blocked(addr)
    if addr is not None:  # pragma: no cover — future address types
        return False

    # Hostname — fall back to the string patterns.
    # Check loopback
    if _LOOPBACK_PATTERNS.match(host_lower):
        return True

    # Check private IPs
    if _PRIVATE_IP_PATTERNS.match(host_lower):
        return True

    # Check link-local
    if _LINKLOCAL_PATTERNS.match(host_lower):
        return True

    # Check cloud metadata endpoints
    if _CLOUD_METADATA_PATTERNS.match(host_lower):
        return True

    return False


# ----------------------------------------------------------------------
# Safe HTTP Client
# ----------------------------------------------------------------------


class SafeHTTPClient:
    """Shared HTTP client with SSRF protections and safe logging.

    All external connector integrations must use this client rather than
    creating their own httpx.AsyncClient instances. Provides:

    - Deterministic timeouts (connect, read, total)
    - SSRF protection (blocks localhost, loopback, private IPs, link-local,
      cloud metadata endpoints)
    - Redirect limits and revalidation
    - Safe logging (never exposes Authorization, keys, tokens, cookies)
    - Deterministic connection pooling

    Example::

        client = SafeHTTPClient(timeout_s=30.0)
        response = await client.get("https://api.example.com/items", params={"page": 1})
        await client.close()
    """

    def __init__(
        self,
        *,
        timeout_s: float = 30.0,
        connect_timeout_s: float | None = None,
        read_timeout_s: float | None = None,
        total_timeout_s: float | None = None,
        max_redirects: int = 5,
        verify_tls: bool = True,
        max_response_bytes: int | None = DEFAULT_MAX_RESPONSE_BYTES,
        allowed_ports: set[int] | frozenset[int] | None = None,
        allowed_hosts: set[str] | frozenset[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.connect_timeout_s = connect_timeout_s or timeout_s
        self.read_timeout_s = read_timeout_s or timeout_s
        self.total_timeout_s = total_timeout_s or timeout_s
        self.max_redirects = max_redirects
        self.verify_tls = verify_tls
        self.max_response_bytes = max_response_bytes
        self.allowed_ports = (
            frozenset(allowed_ports) if allowed_ports is not None else DEFAULT_ALLOWED_PORTS
        )
        # Exact hostname/IP allowlist checked BEFORE the SSRF blocklist
        # (dev/E2E stub escape hatch — normally empty).
        self.allowed_hosts = frozenset(
            h.strip().lower() for h in (allowed_hosts or set()) if h.strip()
        )
        self.transport = transport

        # Shared client instance (created lazily)
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Lazy-create the shared httpx AsyncClient."""
        # The worker creates a fresh event loop per execution. A cached
        # httpx.AsyncClient is bound to whichever loop first opened it,
        # so reusing it in a new loop raises "is bound to a different
        # event loop". Detect a loop change and rebuild the client.
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if self._client is not None and self._client_loop is not current_loop:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        if self._client is None or not self._initialized:
            # httpx 0.28 removed the `total` timeout; connect+read bound
            # the worst case for a single request. Keyword form requires
            # ALL of connect/read/write/pool (httpx 0.28+).
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=self.connect_timeout_s,
                    read=self.read_timeout_s,
                    write=self.read_timeout_s,
                    pool=self.read_timeout_s,
                ),
                follow_redirects=True,
                max_redirects=self.max_redirects,
                verify=self.verify_tls,
                event_hooks={"request": [self._validate_request]},
                transport=self.transport,
            )
            self._initialized = True
            self._client_loop = current_loop
        return self._client

    # ------------------------------------------------------------------
    # Outbound request validation (SSRF / URL policy)
    # ------------------------------------------------------------------

    async def _validate_request(self, request: httpx.Request) -> None:
        """Validate EVERY outbound request, including redirects.

        Enforced as an httpx event hook so redirect targets are checked
        before they are followed, not after. Blocks:
        - non-http(s) schemes
        - non-standard ports (policy)
        - SSRF hosts (loopback, private, link-local, metadata, …)
        """
        scheme = (request.url.scheme or "").lower()
        if scheme not in ("http", "https"):
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"URL scheme '{scheme}' is not allowed.",
                retryable=False,
            )
        port = request.url.port
        if port is None:
            port = 443 if scheme == "https" else 80
        if port not in self.allowed_ports:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"Port {port} is not allowed by policy.",
                retryable=False,
            )
        host = (request.url.host or "").strip("[]")
        if host and host.lower() not in self.allowed_hosts and _is_blocked_host(host):
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"Request blocked by SSRF policy: host '{host}' is not allowed.",
                retryable=False,
            )

    async def close(self) -> None:
        """Close the shared client connection pool."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._initialized = False

    async def __aenter__(self) -> "SafeHTTPClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass  # Pool stays alive — closed only at app shutdown

    # ------------------------------------------------------------------
    # Request building helpers (safe logging / header redaction)
    # ------------------------------------------------------------------

    @staticmethod
    def _redact_sensitive_headers(headers: dict[str, str]) -> dict[str, str]:
        """Redact sensitive header values before logging or forwarding.

        Never logs: Authorization, Proxy-Authorization, WWW-Authenticate,
        cookie, x-api-key, x-auth-token, or any header containing 'secret',
        'token', 'key', or 'credential' (case-insensitive).
        """
        sensitive_prefixes = (
            "authorization",
            "proxy-authorization",
            "www-authenticate",
            "cookie",
            "x-api-key",
            "x-auth-token",
            "x-csrf-token",
        )
        redacted: dict[str, str] = {}
        for k, v in headers.items():
            kl = k.lower()
            if any(kl.startswith(p) or p in kl for p in sensitive_prefixes):
                redacted[k] = "***REDACTED***"
            elif "secret" in kl or "token" in kl or "key" in kl or "credential" in kl:
                redacted[k] = "***REDACTED***"
            else:
                redacted[k] = v
        return redacted

    @staticmethod
    def _sanitize_for_logging(value: Any) -> Any:
        """Sanitize a value for safe logging — never expose secrets."""

        if isinstance(value, str):
            # Mask potential API keys/tokens (long hex strings, base64)
            if len(value) > 20 and re.match(r"^[a-zA-Z0-9\/+=]{20,}$", value):
                return value[:6] + "…" + value[-3:]
            return value[:100] + "…" if len(value) > 100 else value
        if isinstance(value, dict):
            return {k: SafeHTTPClient._sanitize_for_logging(v) for k, v in value.items()}
        if isinstance(value, list):
            return [SafeHTTPClient._sanitize_for_logging(v) for v in value]
        return value

    # ------------------------------------------------------------------
    # Core request methods
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        max_response_bytes: int | None = None,
    ) -> httpx.Response:
        """Execute a request with full SSRF protection and safe logging.

        `timeout` overrides the client default for this request only
        (httpx accepts a float or httpx.Timeout; the `total` field was
        removed in httpx 0.28).

        `max_response_bytes` overrides the client default response-size
        cap for this request only (None = use the client default).

        Raises ConnectorError on blocked hosts, timeouts, or HTTP errors.
        """

        # Phase 14 (workflow testing): test-mode mocks short-circuit
        # ONLY active during workflow test runs (test_spec provided).
        # Production execution never activates mocks.
        from app.security import http_mocks

        mocked = None
        if http_mocks.active_rules() is not None:
            try:
                mocked = http_mocks.intercept(method, url)
            except http_mocks.MockUnmatchedError as exc:
                raise make_connector_error(
                    ConnectorErrorCode.BAD_REQUEST, str(exc), retryable=False,
                ) from exc
            if mocked is not None:
                body_kwargs: dict[str, Any] = {}
                if mocked["json_body"] is not None:
                    body_kwargs["json"] = mocked["json_body"]
                elif mocked["text"] is not None:
                    body_kwargs["text"] = mocked["text"]
                else:
                    body_kwargs["content"] = b""
                return httpx.Response(
                    status_code=mocked["status"],
                    headers=mocked["headers"],
                    request=httpx.Request(method, url),
                    **body_kwargs,
                )

        # Parse URL to extract host
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
        except Exception:
            host = ""

        # SSRF check (fast fail; the request hook re-validates every
        # outbound request, including redirect targets). The exact-match
        # allowlist (dev/E2E stub) is checked before the blocklist.
        if host and host.lower() not in self.allowed_hosts and _is_blocked_host(host):
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"Request blocked by SSRF policy: host '{host}' is not allowed.",
                retryable=False,
            )

        client = await self._ensure_client()

        # Real headers go on the wire unchanged (Authorization, API keys,
        # cookies). Redaction applies only to what is logged below.
        request_headers = dict(headers or {})

        # Safe observability: log the request with sensitive headers
        # redacted — never the real Authorization/API-key values.
        try:
            parsed = urlparse(url)
            safe_target = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        except Exception:
            safe_target = url
        logger.debug(
            "outbound %s %s headers=%s",
            method,
            safe_target,
            SafeHTTPClient._redact_sensitive_headers(request_headers),
        )

        try:
            if max_response_bytes is not None:
                cap = max_response_bytes
            else:
                cap = self.max_response_bytes
            if cap is None:
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                    data=data,
                    headers=request_headers,
                    cookies=cookies,
                    timeout=timeout,
                )
                return response
            return await self._request_with_size_cap(
                client, method, url, cap,
                params=params, json=json, data=data,
                headers=request_headers, cookies=cookies, timeout=timeout,
            )
        except httpx.DecodingError as exc:
            # Salesforce (F5 edge) can send `Content-Encoding: gzip` over a
            # malformed/uncompressed body; httpx then fails with
            # "Error -3 while decompressing data: incorrect header check".
            # Retry once asking for an identity (uncompressed) response.
            if request_headers.get("Accept-Encoding", "").lower() == "identity":
                raise make_connector_error(
                    ConnectorErrorCode.UNAVAILABLE,
                    "HTTP request failed: response body could not be decoded.",
                    retryable=True,
                ) from exc
            retry_headers = dict(request_headers)
            retry_headers["Accept-Encoding"] = "identity"
            logger.info("response decode failed; retrying with Accept-Encoding: identity")
            return await self._request(
                method,
                url,
                params=params,
                json=json,
                data=data,
                headers=retry_headers,
                cookies=cookies,
                timeout=timeout,
                max_response_bytes=max_response_bytes,
            )
        except httpx.TimeoutException as exc:
            raise make_connector_error(
                ConnectorErrorCode.TIMEOUT,
                f"HTTP request timed out after {self.total_timeout_s}s.",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            # Network-level error — don't expose internal details (the
            # exception class is safe to log for diagnosis; never the
            # URL or headers).
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"HTTP request failed: {type(exc).__name__}{f': {exc}' if str(exc) else ''}",
                retryable=True,
            ) from exc

    async def _request_with_size_cap(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        cap: int,
        *,
        params: dict[str, Any] | None,
        json: Any,
        data: Any,
        headers: dict[str, str],
        cookies: dict[str, Any] | None,
        timeout: float | httpx.Timeout | None,
    ) -> httpx.Response:
        """Stream the response body and enforce the size cap.

        Rebuilds the final httpx.Response so callers see the same shape
        as the non-capped path (fully-read content, redirect history).
        """
        async with client.stream(
            method=method,
            url=url,
            params=params,
            json=json,
            data=data,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
        ) as response:
            content = await self._read_limited(response, cap)
            return httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=content,
                request=response.request,
                history=response.history,
            )

    async def _read_limited(self, response: httpx.Response, cap: int) -> bytes:
        """Read the response body, failing fast once the cap is exceeded."""
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > cap:
                raise make_connector_error(
                    ConnectorErrorCode.UNAVAILABLE,
                    f"Response exceeded the maximum allowed size ({cap} bytes).",
                    retryable=False,
                )
            chunks.append(chunk)
        return b"".join(chunks)

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, Any] | None = None,
        auth: Any = None,
        timeout: float | httpx.Timeout | None = None,
        max_response_bytes: int | None = None,
    ) -> httpx.Response:
        """Generic request with SSRF protection and safe logging.

        Mirrors httpx.AsyncClient.request() for callers that build the
        method dynamically.
        """
        request_headers = dict(headers) if headers else {}
        if auth is not None:
            if isinstance(auth, (tuple, list)) and len(auth) == 2:
                import base64
                b64 = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
                request_headers.setdefault("Authorization", f"Basic {b64}")
        return await self._request(
            method,
            url,
            params=params,
            json=json,
            data=data,
            headers=request_headers or None,
            cookies=cookies,
            timeout=timeout,
            max_response_bytes=max_response_bytes,
        )

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        max_response_bytes: int | None = None,
    ) -> httpx.Response:
        """GET request with SSRF protection and safe logging."""
        return await self._request(
            "GET", url, params=params, headers=headers, timeout=timeout,
            max_response_bytes=max_response_bytes,
        )

    async def post(
        self,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        max_response_bytes: int | None = None,
    ) -> httpx.Response:
        """POST request with SSRF protection and safe logging."""
        return await self._request(
            "POST", url, json=json, headers=headers, timeout=timeout,
            max_response_bytes=max_response_bytes,
        )

    async def put(
        self,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        max_response_bytes: int | None = None,
    ) -> httpx.Response:
        """PUT request with SSRF protection and safe logging."""
        return await self._request(
            "PUT", url, json=json, headers=headers, timeout=timeout,
            max_response_bytes=max_response_bytes,
        )

    async def delete(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        max_response_bytes: int | None = None,
    ) -> httpx.Response:
        """DELETE request with SSRF protection and safe logging."""
        return await self._request(
            "DELETE", url, headers=headers, timeout=timeout,
            max_response_bytes=max_response_bytes,
        )

    async def patch(
        self,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        max_response_bytes: int | None = None,
    ) -> httpx.Response:
        """PATCH request with SSRF protection and safe logging."""
        return await self._request(
            "PATCH", url, json=json, headers=headers, timeout=timeout,
            max_response_bytes=max_response_bytes,
        )


# ----------------------------------------------------------------------
# Module-level singleton for convenience
# ----------------------------------------------------------------------


_default_client: SafeHTTPClient | None = None


def get_safe_http_client() -> SafeHTTPClient:
    """Get the default SafeHTTPClient singleton.

    Creates one on first call; the same instance is returned thereafter.
    Configuration can be overridden by creating a new SafeHTTPClient
    instance directly.

    Dev/E2E escape hatch: when `SAFE_HTTP_ALLOWED_HOSTS` /
    `SAFE_HTTP_ALLOWED_PORTS` are set in the environment, the singleton
    allows those exact hosts and ports past the SSRF policy (used by the
    Playwright suite to reach the local Salesforce stub). OFF by default;
    never set these in production.
    """
    global _default_client
    if _default_client is None:
        allowed_hosts = _env_allowed_hosts()
        allowed_ports = _env_allowed_ports()
        if allowed_hosts is not None or allowed_ports is not None:
            # Env entries ADD to the strict defaults (80/443 keep working);
            # they never remove protection. Hosts are an exact-match
            # allowlist checked before the SSRF blocklist.
            if allowed_ports is None:
                allowed_ports = frozenset()
            ports = DEFAULT_ALLOWED_PORTS | allowed_ports
            _default_client = SafeHTTPClient(
                allowed_hosts=allowed_hosts,
                allowed_ports=ports,
            )
        else:
            _default_client = SafeHTTPClient()
    return _default_client


def reset_safe_http_client() -> None:
    """Reset the singleton (use in testing)."""
    global _default_client
    if _default_client is not None:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            # Can't close from outside the running loop; just reset ref
            _default_client = None
        except RuntimeError:
            _default_client = None
    else:
        _default_client = None