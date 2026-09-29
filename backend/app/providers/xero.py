"""Xero accounting provider client (Phase 40).

Integrates with Xero Accounting REST API v2:
https://api.xero.com/api.xro/2.0

Supports:
- list_invoices (GET /Invoices)
- get_invoice (GET /Invoices/{InvoiceID})
- create_invoice (POST /Invoices)
- list_contacts (GET /Contacts)
- get_accounts (GET /Accounts)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.xero")
_extract_xero_error = json_error_message("Message", "Elements")

XERO_API_BASE = "https://api.xero.com/api.xro/2.0"


class XeroProviderClient(BaseProviderClient):
    """Client for Xero Accounting REST API v2."""

    api_base = XERO_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("Xero uses OAuth2 access tokens and refresh tokens.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> tuple[str, str]:
        tenant_id = str(creds.get("tenant_id") or creds.get("tenantId") or "").strip()
        if not tenant_id:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Xero connector requires a 'tenant_id'.",
                retryable=False,
            )
        token = str(creds.get("access_token") or creds.get("token") or "").strip()
        if not token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Xero connector requires an 'access_token'.",
                retryable=False,
            )
        return tenant_id, token

    async def request_xero(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        tenant_id, token = self._validate_creds(creds)
        url = f"{self.api_base}/{path.lstrip('/')}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Xero-Tenant-Id": tenant_id,
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
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"Xero request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Xero request failed: {exc}", retryable=True) from exc

        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text, "status_code": resp.status_code}

        if resp.status_code == 400:
            msg = _extract_xero_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Xero error: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "Xero access token is invalid or expired.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Xero forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Xero resource not found: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "Xero rate limit exceeded.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Xero service error: {resp.status_code}", retryable=True)

        return {"raw": resp.text, "status_code": resp.status_code}

    async def list_invoices(
        self,
        creds: dict[str, Any],
        *,
        where: Optional[str] = None,
        page: int = 1,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if where:
            params["where"] = where
        return await self.request_xero(creds, "GET", "Invoices", params=params, timeout=timeout)

    async def get_invoice(
        self,
        creds: dict[str, Any],
        invoice_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_xero(creds, "GET", f"Invoices/{invoice_id}", timeout=timeout)

    async def create_invoice(
        self,
        creds: dict[str, Any],
        contact_id: str,
        line_items: List[Dict[str, Any]],
        *,
        type_str: str = "ACCREC",
        due_date: Optional[str] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        invoice: dict[str, Any] = {
            "Type": type_str,
            "Contact": {"ContactID": contact_id},
            "LineItems": line_items,
        }
        if due_date:
            invoice["DueDate"] = due_date
        body = {"Invoices": [invoice]}
        return await self.request_xero(creds, "POST", "Invoices", json_body=body, timeout=timeout)

    async def list_contacts(
        self,
        creds: dict[str, Any],
        *,
        page: int = 1,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_xero(creds, "GET", "Contacts", params={"page": page}, timeout=timeout)

    async def get_accounts(
        self,
        creds: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request_xero(creds, "GET", "Accounts", timeout=timeout)
