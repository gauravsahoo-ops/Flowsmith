"""HttpRequestExecutor — separated from node, uses HttpAuthBuilder + provider registry."""
from __future__ import annotations

from typing import Any, Dict

import httpx

from app.engine.errors import NodeExecutionError
from app.engine.node_base import filter_client_kwargs
from .http_auth_builder import get_http_auth_builder


class HttpRequestExecutor:
    """Executes an HTTP request with auth, timeouts, redirects, SSL options."""

    def __init__(self, http_client: Any) -> None:
        self.http_client = http_client

    async def execute(self, request: Dict[str, Any], options: Dict[str, Any]) -> httpx.Response:
        method = request.get("method", "GET")
        url = request.get("url", "")
        headers = request.get("headers")
        query = request.get("query")
        json_body = request.get("json")
        data = request.get("data")
        timeout = options.get("timeout", 30.0)
        follow_redirects = options.get("follow_redirects", True)
        max_response_bytes = options.get("max_response_bytes")
        ignore_ssl = options.get("ignore_ssl", False)
        kwargs: Dict[str, Any] = {
            "headers": headers or None,
            "params": query or None,
            "json": json_body,
            "data": data,
            "timeout": timeout,
            "follow_redirects": follow_redirects,
            "max_response_bytes": max_response_bytes,
        }
        if ignore_ssl:
            kwargs["verify"] = False
        # Filter kwargs to what client supports
        filtered = filter_client_kwargs(self.http_client, kwargs)
        try:
            response = await self.http_client.request(method, url, **filtered)
        except httpx.TimeoutException as e:
            raise NodeExecutionError(f"HTTP timeout after {timeout}s.", code="HTTP_TIMEOUT", retryable=True) from e
        except httpx.RequestError as e:
            raise NodeExecutionError(f"HTTP request failed: {e}", code="HTTP_REQUEST_FAILED", retryable=True) from e
        # Redirect limit
        max_redirects = options.get("max_redirects", 5)
        if follow_redirects and len(getattr(response, "history", [])) > max_redirects:
            raise NodeExecutionError(f"Too many redirects ({len(response.history)} > {max_redirects}).", code="HTTP_TOO_MANY_REDIRECTS", retryable=False)
        return response

    @staticmethod
    def build_request_with_auth(base: Dict[str, Any], provider_id: str | None, cred: Dict[str, Any] | None) -> Dict[str, Any]:
        """Apply auth if provider and cred provided."""
        if not provider_id or not cred:
            return base
        builder = get_http_auth_builder()
        return builder.build(base, provider_id, cred)


_executor_cls = HttpRequestExecutor
