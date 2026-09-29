"""Freshsales CRM provider client (Phase 40).

Integrates with Freshsales REST API:
https://{domain}.freshsales.io/api

Supports:
- list_contacts (GET /contacts)
- get_contact (GET /contacts/{id})
- create_contact (POST /contacts)
- list_deals (GET /deals)
- create_deal (POST /deals)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.freshsales")
_extract_freshsales_error = json_error_message("message", "errors")


class FreshsalesProviderClient(BaseProviderClient):
    """Client for Freshsales REST API."""

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("Freshsales uses API Key tokens.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> tuple[str, str]:
        domain = str(creds.get("domain") or "").strip().lower()
        if not domain:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Freshsales connector requires a 'domain' (e.g. mycompany).",
                retryable=False,
            )
        domain = domain.replace(".freshsales.io", "").strip()
        api_key = str(creds.get("api_key") or creds.get("token") or "").strip()
        if not api_key:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Freshsales connector requires an 'api_key'.",
                retryable=False,
            )
        return domain, api_key

    async def request_freshsales(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        domain, api_key = self._validate_creds(creds)
        url = f"https://{domain}.freshsales.io/api/{path.lstrip('/')}"

        headers = {
            "Authorization": f"Token token={api_key}",
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
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"Freshsales request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Freshsales request failed: {exc}", retryable=True) from exc

        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}

        if resp.status_code == 400:
            msg = _extract_freshsales_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Freshsales error: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "Freshsales API token is invalid.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Freshsales forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Freshsales resource not found: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "Freshsales rate limit exceeded.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Freshsales service error: {resp.status_code}", retryable=True)

        return {"raw": resp.text, "status_code": resp.status_code}

    async def list_contacts(
        self,
        creds: dict[str, Any],
        *,
        page: int = 1,
        per_page: int = 25,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params = {"page": page, "per_page": per_page}
        return await self.request_freshsales(creds, "GET", "contacts", params=params, timeout=timeout)

    async def get_contact(
        self,
        creds: dict[str, Any],
        contact_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_freshsales(creds, "GET", f"contacts/{contact_id}", timeout=timeout)

    async def create_contact(
        self,
        creds: dict[str, Any],
        first_name: str,
        last_name: str,
        email: str,
        *,
        mobile_number: Optional[str] = None,
        job_title: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        contact: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
        }
        if mobile_number:
            contact["mobile_number"] = mobile_number
        if job_title:
            contact["job_title"] = job_title
        return await self.request_freshsales(creds, "POST", "contacts", json_body={"contact": contact}, timeout=timeout)

    async def list_deals(
        self,
        creds: dict[str, Any],
        *,
        page: int = 1,
        per_page: int = 25,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params = {"page": page, "per_page": per_page}
        return await self.request_freshsales(creds, "GET", "deals", params=params, timeout=timeout)

    async def create_deal(
        self,
        creds: dict[str, Any],
        name: str,
        amount: float,
        *,
        sales_account_id: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        deal: dict[str, Any] = {"name": name, "amount": amount}
        if sales_account_id:
            deal["sales_account_id"] = sales_account_id
        return await self.request_freshsales(creds, "POST", "deals", json_body={"deal": deal}, timeout=timeout)
