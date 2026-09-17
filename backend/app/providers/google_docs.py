"""Google Docs provider client.

Google Docs API v1 on the shared Google OAuth app (config_prefix=google).
Accepts a direct access_token (tests/manual tokens) or mints one from the
stored refresh_token via the server-side OAuth app. Ops: get/create
documents, append text, raw batch updates. 429/5xx retryable.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.config import get_settings
from app.security.safe_http_client import get_safe_http_client

GOOGLE_DOCS_API_BASE = "https://docs.googleapis.com/v1/documents"


class GoogleDocsProviderClient:
    def __init__(self) -> None:
        self._access_tokens: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        self._access_tokens.clear()

    async def _access_token(self, creds: dict) -> str:
        direct = str((creds or {}).get("access_token") or "").strip()
        if direct:
            return direct
        refresh_token = str((creds or {}).get("refresh_token") or "").strip()
        if not refresh_token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Google Docs connector needs a 'google_docs' credential — "
                "connect it from the UI ('Connect Google Docs').",
                retryable=False,
            )
        import time

        cached = self._access_tokens.get(refresh_token)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
        async with self._lock:
            cached = self._access_tokens.get(refresh_token)
            if cached and cached[1] > time.time() + 60:
                return cached[0]
            token, expires_at = await self._refresh_access_token(refresh_token)
            self._access_tokens[refresh_token] = (token, expires_at)
            return token

    async def _refresh_access_token(self, refresh_token: str) -> tuple[str, float]:
        from urllib.parse import urlencode

        settings = get_settings()
        if not settings.google_client_id or not settings.google_client_secret:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Google OAuth is not configured on the server "
                "(GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET).",
                retryable=False,
            )
        body = urlencode({
            "grant_type": "refresh_token",
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": refresh_token,
        })
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST", "https://oauth2.googleapis.com/token",
                    data=body, headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=30.0,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Google token endpoint unreachable: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if response.status_code >= 400 or not (payload.get("access_token") if isinstance(payload, dict) else None):
            raise make_connector_error(
                ConnectorErrorCode.AUTH_FAILED, "Google re-authentication failed.", retryable=False)
        expires_in = payload.get("expires_in", 3600)
        try:
            expires_at = time.time() + float(expires_in)
        except (TypeError, ValueError):
            expires_at = time.time() + 3600
        return str(payload["access_token"]), expires_at

    async def _request(
        self, creds: dict, method: str, path: str, what: str,
        params: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict:
        token = await self._access_token(creds)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{GOOGLE_DOCS_API_BASE}{path}",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    params=params or {}, json=body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Google Docs unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        self._raise(response.status_code, response.text, what, payload)
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
        detail = ""
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict) and err.get("message"):
                detail = f": {str(err['message'])[:200]}"
        if status < 400:
            return
        if status == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Google Docs auth failed during {what}{detail}.", retryable=False)
        if status == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Google Docs forbade {what}{detail}.", retryable=False)
        if status == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Google Docs document missing during {what}{detail}.", retryable=False)
        if status == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Google Docs rate limited during {what}{detail}.", retryable=True)
        if status >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Google Docs unavailable during {what}{detail}.", retryable=True)
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Google Docs rejected {what}{detail or ': ' + body[:200]}.", retryable=False)

    async def test_connection(self, creds: dict) -> dict:
        """Probe without side effects: empty list call is not available, so
        validate the token against Google's tokeninfo endpoint."""
        token = await self._access_token(creds)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "GET", "https://oauth2.googleapis.com/tokeninfo",
                    params={"access_token": token}, timeout=15.0,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Google tokeninfo unreachable: {exc}", retryable=True,
            ) from exc
        if response.status_code >= 400:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "Google Docs token is invalid.", retryable=False)
        return {"ok": True, "message": "Connected."}

    async def get_document(self, creds: dict, document_id: str, timeout: float = 30.0) -> dict:
        if not str(document_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_document needs a document_id.", retryable=False)
        return await self._request(creds, "GET", f"/{document_id}", "get_document", timeout=timeout)

    async def create_document(self, creds: dict, title: str, timeout: float = 30.0) -> dict:
        if not str(title or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_document needs a title.", retryable=False)
        return await self._request(creds, "POST", "", "create_document", body={"title": title}, timeout=timeout)

    async def append_text(self, creds: dict, document_id: str, text: str, timeout: float = 30.0) -> dict:
        if not str(document_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "append_text needs a document_id.", retryable=False)
        if text is None:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "append_text needs text.", retryable=False)
        doc = await self.get_document(creds, document_id, timeout=timeout)
        end_index = 1
        try:
            content = doc.get("body", {}).get("content", [])
            if content:
                end_index = max(int(el.get("endIndex", 1)) for el in content if isinstance(el, dict))
        except (TypeError, ValueError):
            end_index = 1
        return await self._request(
            creds, "POST", f"/{document_id}:batchUpdate", "append_text",
            body={"requests": [{"insertText": {"location": {"index": max(end_index - 1, 1)}, "text": str(text)}}]},
            timeout=timeout,
        )

    async def batch_update(self, creds: dict, document_id: str, requests: list[dict[str, Any]], timeout: float = 30.0) -> dict:
        if not str(document_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "batch_update needs a document_id.", retryable=False)
        if not requests:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "batch_update needs requests.", retryable=False)
        return await self._request(creds, "POST", f"/{document_id}:batchUpdate", "batch_update",
                                   body={"requests": requests}, timeout=timeout)
