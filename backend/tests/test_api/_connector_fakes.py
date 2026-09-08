"""Shared test fakes for Phase 11 business-connector suites.

A scripted SafeHTTPClient replacement: records every call and returns
queued responses in order (exceptions may be queued too). Patch targets
are per-provider modules, so each suite passes its own module path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


class FakeHTTPClient:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(self, method, url, **kwargs) -> httpx.Response:
        self.calls.append((method.upper(), url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected extra call: {method} {url}")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def json_response(status: int, payload: Any, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers or {}, request=httpx.Request("GET", "http://fake"))


def empty_response(status: int = 204, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, content=b"", headers=headers or {}, request=httpx.Request("GET", "http://fake"))


class _PatcherGroup:
    def __init__(self, patchers) -> None:
        self._patchers = patchers
        for p in patchers:
            p.start()

    def stop(self) -> None:
        for p in self._patchers:
            p.stop()


def patch_provider_http(module_path: str | list[str], responses: list[httpx.Response | Exception]):
    """Patch ``get_safe_http_client`` inside one or more modules; returns
    (group, fake_client) so suites can assert on recorded calls.

    Providers that go through ``BaseProviderClient.authorized_request``
    resolve the client from ``app.providers.base``, so suites pass that
    path alongside (or instead of) their own module.
    """
    if isinstance(module_path, str):
        module_path = [module_path]
    fake = FakeHTTPClient(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    group = _PatcherGroup([patch(f"{m}.get_safe_http_client", return_value=cm) for m in module_path])
    return group, fake
