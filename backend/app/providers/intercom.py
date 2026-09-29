"""Intercom customer messaging provider client (Phase 40).

Integrates with Intercom REST API:
https://api.intercom.io

Supports:
- list_conversations (GET /conversations)
- get_conversation (GET /conversations/{id})
- reply_conversation (POST /conversations/{id}/reply)
- list_contacts (GET /contacts)
- create_contact (POST /contacts)
- search_contacts (POST /contacts/search)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.intercom")
_extract_intercom_error = json_error_message("errors", "message")

INTERCOM_API_BASE = "https://api.intercom.io"


class IntercomProviderClient(BaseProviderClient):
    """Client for Intercom REST API."""

    api_base = INTERCOM_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("Intercom uses Bearer Access Tokens or OAuth.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> str:
        token = str(creds.get("access_token") or creds.get("token") or creds.get("api_key") or "").strip()
        if not token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Intercom connector requires an 'access_token'.",
                retryable=False,
            )
        return token

    async def request_intercom(
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
            "Intercom-Version": "2.11",
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
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"Intercom request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Intercom request failed: {exc}", retryable=True) from exc

        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}

        if resp.status_code == 400:
            msg = _extract_intercom_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Intercom error: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "Intercom access token is invalid or expired.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Intercom access forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Intercom resource not found: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "Intercom rate limit reached.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Intercom service error: {resp.status_code}", retryable=True)

        return {"raw": resp.text, "status_code": resp.status_code}

    async def list_conversations(
        self,
        creds: dict[str, Any],
        *,
        per_page: int = 25,
        starting_after: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"per_page": per_page}
        if starting_after:
            params["starting_after"] = starting_after
        return await self.request_intercom(creds, "GET", "conversations", params=params, timeout=timeout)

    async def get_conversation(
        self,
        creds: dict[str, Any],
        conversation_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_intercom(creds, "GET", f"conversations/{conversation_id}", timeout=timeout)

    async def reply_conversation(
        self,
        creds: dict[str, Any],
        conversation_id: str,
        body_text: str,
        *,
        message_type: str = "comment",
        admin_id: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "message_type": message_type,
            "type": "admin",
            "body": body_text,
        }
        if admin_id:
            payload["admin_id"] = admin_id
        return await self.request_intercom(creds, "POST", f"conversations/{conversation_id}/reply", json_body=payload, timeout=timeout)

    async def list_contacts(
        self,
        creds: dict[str, Any],
        *,
        per_page: int = 50,
        starting_after: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"per_page": per_page}
        if starting_after:
            params["starting_after"] = starting_after
        return await self.request_intercom(creds, "GET", "contacts", params=params, timeout=timeout)

    async def create_contact(
        self,
        creds: dict[str, Any],
        *,
        email: Optional[str] = None,
        name: Optional[str] = None,
        role: str = "user",
        custom_attributes: Optional[dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"role": role}
        if email:
            body["email"] = email
        if name:
            body["name"] = name
        if custom_attributes:
            body["custom_attributes"] = custom_attributes
        return await self.request_intercom(creds, "POST", "contacts", json_body=body, timeout=timeout)

    async def search_contacts(
        self,
        creds: dict[str, Any],
        query: dict[str, Any],
        *,
        pagination: Optional[dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"query": query}
        if pagination:
            body["pagination"] = pagination
        return await self.request_intercom(creds, "POST", "contacts/search", json_body=body, timeout=timeout)
