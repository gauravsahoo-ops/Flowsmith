"""Typeform provider client (Phase 39).

Integrates with Typeform REST API v2:
https://api.typeform.com

Supports:
- list_forms (GET /forms)
- get_form (GET /forms/{form_id})
- get_responses (GET /forms/{form_id}/responses)
- create_webhook (PUT /forms/{form_id}/webhooks/{tag})
- delete_webhook (DELETE /forms/{form_id}/webhooks/{tag})
- test_connection (GET /me)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.typeform")
_extract_typeform_error = json_error_message("description", "code")

TYPEFORM_API_BASE = "https://api.typeform.com"


class TypeformProviderClient(BaseProviderClient):
    """Client for Typeform REST API v2."""

    api_base = TYPEFORM_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("Typeform connector uses Personal Access Tokens or Bearer tokens.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> str:
        token = str(creds.get("token") or creds.get("api_key") or creds.get("access_token") or "").strip()
        if not token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Typeform connector requires a 'token' or 'api_key' (Personal Access Token).",
                retryable=False,
            )
        return token

    async def request_typeform(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        token = self._validate_creds(creds)
        url = f"{self.api_base}/{path.lstrip('/')}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            async with get_safe_http_client() as client:
                resp = await client.request(
                    method.upper(),
                    url,
                    headers=headers,
                    params=params,
                    json=json_body if json_body is not None else None,
                    timeout=timeout,
                )
        except httpx.TimeoutException as exc:
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"Typeform request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Typeform request failed: {exc}", retryable=True) from exc

        if resp.status_code == 204:
            return {"deleted": True, "status_code": 204}

        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}

        if resp.status_code == 400:
            msg = _extract_typeform_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Typeform bad request: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "Typeform access token is invalid.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Typeform forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Typeform resource not found: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "Typeform rate limit exceeded.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Typeform service unavailable: {resp.status_code}", retryable=True)

        return {"raw": resp.text, "status_code": resp.status_code}

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        return await self.request_typeform(creds, "GET", "me")

    async def list_forms(
        self,
        creds: dict[str, Any],
        *,
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
        workspace_id: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if search:
            params["search"] = search
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self.request_typeform(creds, "GET", "forms", params=params, timeout=timeout)

    async def get_form(
        self,
        creds: dict[str, Any],
        form_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_typeform(creds, "GET", f"forms/{form_id}", timeout=timeout)

    async def get_responses(
        self,
        creds: dict[str, Any],
        form_id: str,
        *,
        page_size: int = 25,
        since: Optional[str] = None,
        until: Optional[str] = None,
        completed: Optional[bool] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": page_size}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if completed is not None:
            params["completed"] = "true" if completed else "false"
        return await self.request_typeform(creds, "GET", f"forms/{form_id}/responses", params=params, timeout=timeout)

    async def create_webhook(
        self,
        creds: dict[str, Any],
        form_id: str,
        tag: str,
        url: str,
        *,
        secret: Optional[str] = None,
        enabled: bool = True,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "url": url,
            "enabled": enabled,
        }
        if secret:
            body["secret"] = secret
        return await self.request_typeform(creds, "PUT", f"forms/{form_id}/webhooks/{tag}", json_body=body, timeout=timeout)

    async def delete_webhook(
        self,
        creds: dict[str, Any],
        form_id: str,
        tag: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_typeform(creds, "DELETE", f"forms/{form_id}/webhooks/{tag}", timeout=timeout)
