"""HTTP mocking for test runs (Phase 14: first-class workflow testing).

Test executions install mock rules into a ContextVar; SafeHTTPClient
consults it before every outbound call. Two guarantees:

1. A matched rule answers locally — the real provider is never contacted.
2. While mocks are installed, an UNMATCHED outbound request is blocked
   with a typed error. Test mode can therefore never mutate production
   data through any node or connector that uses the shared client.

The ContextVar propagates into asyncio child tasks, so parallel branches
inside the execution are covered too. Pure sync logic; unit-tested.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error


@dataclass(frozen=True)
class MockRule:
    """One canned response. ``url_pattern`` is a glob (* wildcard); an
    empty/``*`` method matches any verb."""

    url_pattern: str
    method: str = "*"
    status: int = 200
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    text: str | None = None


_active: ContextVar[tuple[tuple[MockRule, re.Pattern], ...] | None] = ContextVar(
    "http_mocks", default=None
)


def compile_rules(rules: list[dict[str, Any]] | None) -> tuple[tuple[MockRule, re.Pattern], ...]:
    """Build (rule, compiled-matcher) pairs from API-shaped dicts.

    Matching semantics:
    - ``*`` / ``**`` wildcards via fnmatch on the full URL;
    - method compared case-insensitively (``*``/empty = any);
    - pattern without a scheme is anchored to the end of the URL so
      ``api.example.com/v1/x`` matches https and http alike.
    """
    compiled: list[tuple[MockRule, re.Pattern]] = []
    for raw in rules or []:
        pattern = str(raw.get("url_pattern") or "").strip()
        if not pattern:
            continue
        method = str(raw.get("method") or "*").strip().upper() or "*"
        regex_text = _glob_to_regex(pattern)
        compiled.append((
            MockRule(
                url_pattern=pattern,
                method=method,
                status=int(raw.get("status") or 200),
                body=raw.get("body"),
                headers={str(k): str(v) for k, v in (raw.get("headers") or {}).items()},
                text=raw.get("text"),
            ),
            re.compile(regex_text, re.IGNORECASE),
        ))
    return tuple(compiled)


def _glob_to_regex(pattern: str) -> str:
    # Escape literals verbatim; '*' becomes a wildcard segment. The old
    # implementation prefixed EVERY character with '.', silently doubling
    # the required input length so patterns could never match.
    parts: list[str] = []
    for ch in pattern:
        parts.append(".*" if ch == "*" else re.escape(ch))
    escaped = "".join(parts)
    if "://" not in pattern:
        # Anchor host-only patterns to the tail of the URL, tolerating a
        # trailing query string so "host/path" matches "host/path?x=1".
        return f"{escaped}(?:\\?.*)?$"
    return f"^{escaped}$"


def install(rules_compiled: tuple) -> Any:
    """Activate the given compiled rules; returns a reset token."""
    return _active.set(rules_compiled or ())


def reset(token: Any) -> None:
    _active.reset(token)


def active_rules() -> tuple[tuple[MockRule, re.Pattern], ...] | None:
    return _active.get()


class MockUnmatchedError(Exception):
    """Raised in strict test mode when an outbound call has no mock."""

    def __init__(self, method: str, url: str) -> None:
        self.method = method
        self.url = url
        super().__init__(
            f"Test mode blocked {method} {url}: no mock matched "
            "(production systems are never contacted during tests)."
        )


def intercept(method: str, url: str):
    """Return a mocked response spec when a rule matches.

    - match  -> dict(status, json_body|text, headers)
    - strict miss while mocks are active -> raises MockUnmatchedError
    - no mocks installed -> None (normal traffic)
    """
    rules = _active.get()
    if rules is None:
        return None
    method_up = str(method).upper()
    for rule, matcher in rules:
        if rule.method not in ("*", "") and rule.method != method_up:
            continue
        if matcher.search(url):
            return {
                "status": rule.status,
                "json_body": rule.body,
                "text": rule.text,
                "headers": dict(rule.headers),
            }
    raise MockUnmatchedError(method_up, url)


def connector_error_from(exc: MockUnmatchedError):
    return make_connector_error(
        ConnectorErrorCode.BAD_REQUEST,
        str(exc),
        retryable=False,
    )


def _mocked_response(method: str, url: str, mocked: dict[str, Any]):
    """Materialize an httpx.Response from a matched rule."""
    import httpx

    body_kwargs: dict[str, Any] = {}
    if mocked.get("json_body") is not None:
        body_kwargs["json"] = mocked["json_body"]
    elif mocked.get("text") is not None:
        body_kwargs["text"] = mocked["text"]
    else:
        body_kwargs["content"] = b""
    return httpx.Response(
        status_code=int(mocked.get("status") or 200),
        headers=dict(mocked.get("headers") or {}),
        request=httpx.Request(method, url),
        **body_kwargs,
    )


class MockedHttpClient:
    """Test-mode drop-in around the shared execution client.

    Every outbound call consults the active mock rules FIRST: a match
    answers locally (the provider is never contacted), an unmatched
    call raises a typed error (production can never be mutated).
    Everything else delegates to the wrapped client. ``__getattr__``
    passes the rest through so nodes see one coherent interface.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def request(self, method: str, url: str, **kwargs: Any):
        method_up = str(method).upper()
        try:
            mocked = intercept(method_up, str(url))
        except MockUnmatchedError as exc:
            raise connector_error_from(exc) from exc
        if mocked is not None:
            return _mocked_response(method_up, str(url), mocked)
        from app.engine.node_base import filter_client_kwargs

        return await self._inner.request(
            method, url, **filter_client_kwargs(self._inner, kwargs),
        )

    async def get(self, url: str, **kwargs: Any):
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any):
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any):
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any):
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any):
        return await self.request("DELETE", url, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
