"""ActiveCampaign provider client (Phase 40).

Integrates with ActiveCampaign REST API v3:
https://{account}.api-us1.com/api/3

Supports:
- list_contacts (GET /contacts)
- get_contact (GET /contacts/{id})
- create_contact (POST /contacts)
- list_lists (GET /lists)
- list_campaigns (GET /campaigns)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.activecampaign")
_extract_activecampaign_error = json_error_message("message", "errors")


class ActiveCampaignProviderClient(BaseProviderClient):
    """Client for ActiveCampaign REST API v3."""

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("ActiveCampaign uses API Keys.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> tuple[str, str]:
        account = str(creds.get("account") or creds.get("subdomain") or "").strip().lower()
        if not account:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "ActiveCampaign connector requires an 'account' name (e.g. 'myaccount').",
                retryable=False,
            )
        account = account.replace(".api-us1.com", "").replace(".activehosted.com", "").strip()
        api_key = str(creds.get("api_key") or creds.get("token") or "").strip()
        if not api_key:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "ActiveCampaign connector requires an 'api_key'.",
                retryable=False,
            )
        return account, api_key

    async def request_activecampaign(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        account, api_key = self._validate_creds(creds)
        url = f"https://{account}.api-us1.com/api/3/{path.lstrip('/')}"

        headers = {
            "Api-Token": api_key,
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
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"ActiveCampaign request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"ActiveCampaign request failed: {exc}", retryable=True) from exc

        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}

        if resp.status_code == 400:
            msg = _extract_activecampaign_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"ActiveCampaign error: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "ActiveCampaign API token is invalid.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"ActiveCampaign forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"ActiveCampaign resource not found: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "ActiveCampaign rate limit exceeded.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"ActiveCampaign service error: {resp.status_code}", retryable=True)

        return {"raw": resp.text, "status_code": resp.status_code}

    async def list_contacts(
        self,
        creds: dict[str, Any],
        *,
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        return await self.request_activecampaign(creds, "GET", "contacts", params=params, timeout=timeout)

    async def get_contact(
        self,
        creds: dict[str, Any],
        contact_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_activecampaign(creds, "GET", f"contacts/{contact_id}", timeout=timeout)

    async def create_contact(
        self,
        creds: dict[str, Any],
        email: str,
        *,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        phone: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        contact: dict[str, Any] = {"email": email}
        if first_name:
            contact["firstName"] = first_name
        if last_name:
            contact["lastName"] = last_name
        if phone:
            contact["phone"] = phone
        body = {"contact": contact}
        return await self.request_activecampaign(creds, "POST", "contacts", json_body=body, timeout=timeout)

    async def list_lists(
        self,
        creds: dict[str, Any],
        *,
        limit: int = 50,
        offset: int = 0,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params = {"limit": limit, "offset": offset}
        return await self.request_activecampaign(creds, "GET", "lists", params=params, timeout=timeout)

    async def list_campaigns(
        self,
        creds: dict[str, Any],
        *,
        limit: int = 50,
        offset: int = 0,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params = {"limit": limit, "offset": offset}
        return await self.request_activecampaign(creds, "GET", "campaigns", params=params, timeout=timeout)
