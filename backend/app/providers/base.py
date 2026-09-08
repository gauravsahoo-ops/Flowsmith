"""Universal provider-client base (Phase 40).

Extracts the machinery every first-party provider duplicated:

- OAuth refresh-on-demand with an in-memory access-token cache
- one-shot 401 retry after forcing a re-refresh
- Salesforce-style error taxonomy mapping (status -> ConnectorErrorCode
  with retryability), including safe message extraction

Providers extend :class:`BaseProviderClient` and implement ``_refresh``
plus thin verb methods that call :meth:`request`. Salesforce predates
this base and remains compliant via its own implementation (reference
implementation); newer providers (Google Calendar / Sheets / HubSpot)
inherit from here or follow the same contract.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client


def _encode_form(body: dict[str, Any]) -> str:
    """Url-encode a flat form body (values stringified)."""
    return urlencode({k: v for k, v in body.items() if v is not None})


def json_error_message(*keys: str):
    """Build an ``extract_error_message`` callable pulling the first
    non-empty key out of a JSON error body (top level or nested under
    ``error``) — covers nearly every provider's shape."""

    def _extract(response: httpx.Response) -> str:
        try:
            data = response.json()
        except Exception:
            return ""
        if not isinstance(data, dict):
            return ""
        candidates = [data]
        err = data.get("error")
        if isinstance(err, dict):
            candidates.append(err)
        elif isinstance(err, str) and "error" in keys:
            return err[:300]
        for source in candidates:
            for key in keys:
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:300]
        return ""

    return _extract


class BaseProviderClient:
    """Shared OAuth2 client-credentials-refresh plumbing."""

    api_base: str = ""
    token_url: str = ""

    def __init__(self) -> None:
        self._access_tokens: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        self._access_tokens.clear()

    # -- subclasses implement -----------------------------------------

    def _client_id_secret(self) -> tuple[str, str]:
        raise NotImplementedError

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        """POST the refresh grant; return (access_token, expires_at_epoch)."""
        raise NotImplementedError

    # -- shared machinery ---------------------------------------------

    @staticmethod
    def _not_configured() -> ConnectorErrorCode:
        return ConnectorErrorCode.NOT_CONFIGURED

    async def _get_access_token(
        self, creds: dict[str, Any], *, private_token_field: str | None = None
    ) -> str:
        """Resolve a bearer token: static private field first (optional),
        else mint from the encrypted refresh token (cached)."""
        if private_token_field:
            private = str(creds.get(private_token_field) or "").strip()
            if private:
                return private
        refresh_token = str(creds.get("refresh_token") or "").strip()
        if not refresh_token:
            raise make_connector_error(
                self._not_configured(),
                "Credential has no usable auth material.",
                retryable=False,
            )
        async with self._lock:
            cached = self._access_tokens.get(refresh_token)
            if cached and cached[1] > time.monotonic():
                return cached[0]
            settings_client_id, settings_client_secret = self._client_id_secret()
            if not settings_client_id or not settings_client_secret:
                raise make_connector_error(
                    ConnectorErrorCode.NOT_CONFIGURED,
                    "Provider OAuth is not configured on the server.",
                    retryable=False,
                )
            try:
                async with get_safe_http_client() as client:
                    response = await self._post_refresh(client, refresh_token)
            except httpx.TimeoutException as exc:
                raise make_connector_error(ConnectorErrorCode.TIMEOUT, "Token endpoint timed out.", retryable=True) from exc
            except Exception as exc:
                raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Token endpoint unreachable: {exc}", retryable=True) from exc
            if response.status_code >= 400:
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED,
                    "Provider rejected the refresh token; reconnect the account.",
                    retryable=False,
                )
            try:
                data = response.json()
                token = data["access_token"]
                expires_in = float(data.get("expires_in", 1800))
            except (ValueError, KeyError) as exc:
                raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "Token response malformed.", retryable=False) from exc
            expires_at = time.monotonic() + max(expires_in - 60.0, 30.0)
            self._access_tokens[refresh_token] = (token, expires_at)
            return token

    async def _post_refresh(self, http_client: Any, refresh_token: str) -> httpx.Response:
        from urllib.parse import urlencode

        client_id, client_secret = self._client_id_secret()
        body = urlencode({
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        })
        return await http_client.request(
            "POST",
            self.token_url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )

    @staticmethod
    def _map_status_error(status_code: int, what: str) -> tuple[ConnectorErrorCode, bool]:
        code = ConnectorErrorCode.BAD_REQUEST
        retryable = False
        if status_code == 401:
            code, retryable = ConnectorErrorCode.AUTH_FAILED, False
        elif status_code == 403:
            code, retryable = ConnectorErrorCode.FORBIDDEN, False
        elif status_code == 404:
            code, retryable = ConnectorErrorCode.NOT_FOUND, False
        elif status_code == 429:
            code, retryable = ConnectorErrorCode.RATE_LIMITED, True
        elif status_code >= 500:
            code, retryable = ConnectorErrorCode.UNAVAILABLE, True
        return code, retryable

    async def authorized_request(
        self,
        *,
        creds: dict[str, Any],
        method: str,
        url: str,
        json_body: Any = None,
        form_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers_extra: dict[str, str] | None = None,
        timeout: float = 30.0,
        what: str = "request",
        private_token_field: str | None = None,
        auth_scheme: str = "Bearer",
        extract_error_message=None,
        on_response=None,
    ) -> httpx.Response:
        """One authenticated call with one-shot 401 refresh/retry.

        ``headers_extra`` merges provider-specific headers (e.g.
        ``Notion-Version``) after the Authorization header; ``form_body``
        switches the body to url-encoded form data (Stripe-style APIs);
        ``auth_scheme`` overrides the "Bearer" prefix ("Bot" for Discord).
        ``on_response`` runs before generic >=400 handling so providers can
        map header-level signals (GitHub rate-limit budget) first.
        """
        token = await self._get_access_token(creds, private_token_field=private_token_field)
        # Static-token providers (no refresh_token) can never benefit from
        # a 401 re-mint — retrying would just double the request.
        can_refresh = bool(str(creds.get("refresh_token") or "").strip())
        force = False
        while True:
            headers = {
                "Authorization": f"{auth_scheme} {token}".strip(),
                "Accept-Encoding": "identity",
                **(headers_extra or {}),
            }
            try:
                async with get_safe_http_client() as client:
                    response = await client.request(
                        method, url, json=json_body or None,
                        data=_encode_form(form_body) if form_body else None,
                        params=params or None,
                        headers=headers, timeout=timeout,
                    )
            except httpx.TimeoutException as exc:
                raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"{what} timed out.", retryable=True) from exc
            except Exception as exc:
                raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Endpoint unreachable: {exc}", retryable=True) from exc

            if response.status_code == 401 and not force and can_refresh:
                rt = str(creds.get("refresh_token") or "").strip()
                self._access_tokens.pop(rt, None)
                token = await self._get_access_token(creds, private_token_field=private_token_field)
                force = True
                continue

            if response.status_code >= 400:
                if on_response is not None:
                    # Subclass hook: may raise a provider-specific typed
                    # error (e.g. GitHub's header-based rate-limit check).
                    on_response(response)
                detail = extract_error_message(response) if extract_error_message else ""
                code, retryable = self._map_status_error(response.status_code, what)
                raise make_connector_error(code, f"{what} failed ({response.status_code}). {detail}".strip(), retryable=retryable)
            return response
