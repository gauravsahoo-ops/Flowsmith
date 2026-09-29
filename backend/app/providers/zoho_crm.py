"""Zoho CRM provider client (Phase 40).

Integrates with Zoho CRM REST API v2:
https://www.zohoapis.com/crm/v2

Supports:
- list_records (GET /crm/v2/{module})
- get_record (GET /crm/v2/{module}/{id})
- create_records (POST /crm/v2/{module})
- update_records (PUT /crm/v2/{module})
- search_records (GET /crm/v2/{module}/search)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.zoho_crm")
_extract_zoho_error = json_error_message("message", "code")

ZOHO_API_BASE = "https://www.zohoapis.com/crm/v2"


class ZohoCrmProviderClient(BaseProviderClient):
    """Client for Zoho CRM REST API v2."""

    api_base = ZOHO_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("Zoho uses Zoho OAuth tokens.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> str:
        token = str(creds.get("access_token") or creds.get("token") or creds.get("api_key") or "").strip()
        if not token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Zoho CRM connector requires an 'access_token'.",
                retryable=False,
            )
        return token

    async def request_zoho(
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
            "Authorization": f"Zoho-oauthtoken {token}",
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
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"Zoho CRM request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Zoho CRM request failed: {exc}", retryable=True) from exc

        if resp.status_code in (200, 201, 202):
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}

        if resp.status_code == 400:
            msg = _extract_zoho_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Zoho CRM error: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "Zoho CRM access token is invalid or expired.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Zoho CRM access forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Zoho CRM resource not found: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "Zoho CRM rate limit reached.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Zoho CRM service error: {resp.status_code}", retryable=True)

        return {"raw": resp.text, "status_code": resp.status_code}

    async def list_records(
        self,
        creds: dict[str, Any],
        module: str = "Leads",
        *,
        page: int = 1,
        per_page: int = 50,
        fields: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if fields:
            params["fields"] = fields
        return await self.request_zoho(creds, "GET", module, params=params, timeout=timeout)

    async def get_record(
        self,
        creds: dict[str, Any],
        module: str,
        record_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_zoho(creds, "GET", f"{module}/{record_id}", timeout=timeout)

    async def create_records(
        self,
        creds: dict[str, Any],
        module: str,
        data: List[Dict[str, Any]],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body = {"data": data}
        return await self.request_zoho(creds, "POST", module, json_body=body, timeout=timeout)

    async def update_records(
        self,
        creds: dict[str, Any],
        module: str,
        data: List[Dict[str, Any]],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body = {"data": data}
        return await self.request_zoho(creds, "PUT", module, json_body=body, timeout=timeout)

    async def search_records(
        self,
        creds: dict[str, Any],
        module: str,
        *,
        criteria: Optional[str] = None,
        email: Optional[str] = None,
        word: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if criteria:
            params["criteria"] = criteria
        elif email:
            params["email"] = email
        elif word:
            params["word"] = word
        return await self.request_zoho(creds, "GET", f"{module}/search", params=params, timeout=timeout)
