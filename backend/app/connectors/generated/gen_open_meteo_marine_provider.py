"""Generated provider — do not hand-edit, regenerate from the OpenAPI spec.

Source API: Open-Meteo Marine Weather Forecast API
Base URL: https://marine-api.open-meteo.com
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client


API_BASE = "https://marine-api.open-meteo.com"
AUTH_KIND = "none"
AUTH_NAME = ""


def _auth_parts(creds: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Return (headers, query) auth material.

    Empty credentials pass through unauthenticated — public endpoints
    work, protected ones answer 401 (mapped to AUTH_FAILED)."""
    return {}, {}


def _raise_for_status(status: int, body: str, what: str) -> None:
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f'Auth failed during {what}.', retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f'Forbidden during {what}.', retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f'Resource missing during {what}.', retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f'Rate limited during {what}.', retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f'Service unavailable during {what}.', retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f'Request rejected during {what}: {body[:200]}', retryable=False)


class GeneratedProvider:
    """Thin REST client for one generated connector."""

    async def call(
        self, creds: dict, method: str, path_template: str,
        path_values: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        body: Any = None, timeout: float = 30.0, what: str = 'request',
    ) -> Any:
        if not API_BASE:
            raise make_connector_error(ConnectorErrorCode.NOT_CONFIGURED, "No server URL in the imported spec.", retryable=False)
        headers, auth_query = _auth_parts(creds)
        path = path_template
        for name, value in (path_values or {}).items():
            from urllib.parse import quote as _quote
            path = path.replace('{' + str(name) + '}', _quote(str(value), safe=''))
        params = {**auth_query, **(query or {})}
        try:
            async with get_safe_http_client() as client:
                kwargs: dict[str, Any] = {'timeout': timeout}
                if body is not None:
                    kwargs['json'] = body
                response = await client.request(method, API_BASE + path, headers=headers or None, params=params or None, **kwargs)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f'Unreachable during {what}: {exc}', retryable=True) from exc
        _raise_for_status(response.status_code, response.text, what)
        try:
            return response.json()
        except Exception:
            return {'raw': response.text}
