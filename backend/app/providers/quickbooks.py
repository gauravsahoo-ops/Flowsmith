"""QuickBooks provider client.

QuickBooks Online REST API v3 with OAuth2 Bearer access token.
Company-scoped base URL (production or sandbox). Ops: raw query,
company info, customer CRUD, invoice create/get. 429/5xx retryable.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

QUICKBOOKS_PROD_HOST = "https://quickbooks.api.intuit.com"
QUICKBOOKS_SANDBOX_HOST = "https://sandbox-quickbooks.api.intuit.com"
QUICKBOOKS_MINOR_VERSION = "65"


def _auth(creds: dict) -> tuple[str, str, str]:
    token = str((creds or {}).get("access_token") or "").strip()
    realm_id = str((creds or {}).get("realm_id") or "").strip()
    if not token or not realm_id:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "QuickBooks connector needs a 'quickbooks' credential with access_token and realm_id.",
            retryable=False,
        )
    host = QUICKBOOKS_SANDBOX_HOST if str((creds or {}).get("use_sandbox", True)).lower() not in ("false", "0", "no") else QUICKBOOKS_PROD_HOST
    # Explicit production override wins over the sandbox default.
    if str((creds or {}).get("environment") or "").strip().lower() == "production":
        host = QUICKBOOKS_PROD_HOST
    return token, f"{host}/v3/company/{realm_id}", realm_id


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    detail = ""
    if isinstance(payload, dict):
        fault = payload.get("Fault") or {}
        errs = fault.get("Error") or []
        if errs and isinstance(errs[0], dict) and errs[0].get("Message"):
            detail = f": {str(errs[0]['Message'])[:200]}"
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"QuickBooks auth failed during {what}{detail}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"QuickBooks forbade {what}{detail}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"QuickBooks resource missing during {what}{detail}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"QuickBooks rate limited during {what}{detail}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"QuickBooks unavailable during {what}{detail}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"QuickBooks rejected {what}{detail or ': ' + body[:200]}.", retryable=False)


class QuickBooksProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (company info)."""
        data = await self.get_company(creds)
        name = ((data.get("CompanyInfo") or {}) if isinstance(data, dict) else {}).get("CompanyName", "")
        return {"ok": True, "message": f"Connected to {name}." if name else "Connected."}

    async def _request(
        self, creds: dict, method: str, path: str, what: str,
        params: dict[str, Any] | None = None, body: Any = None,
        content_type: str = "application/json", timeout: float = 30.0,
    ) -> dict:
        token, base, _realm = _auth(creds)
        query = {"minorversion": QUICKBOOKS_MINOR_VERSION, **(params or {})}
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{base}{path}",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": content_type, "Accept": "application/json"},
                    params=query,
                    **({"json": body} if content_type == "application/json" else {"data": body}),
                    timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"QuickBooks unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload if isinstance(payload, dict) else {}

    async def query(self, creds: dict, query: str, timeout: float = 30.0) -> dict:
        if not str(query or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "query needs a QuickBooks query string.", retryable=False)
        return await self._request(creds, "POST", "/query", "query", body=query,
                                   content_type="application/text", timeout=timeout)

    async def get_company(self, creds: dict, timeout: float = 30.0) -> dict:
        _, _, realm_id = _auth(creds)
        return await self._request(creds, "GET", f"/companyinfo/{realm_id}", "get_company", timeout=timeout)

    async def create_customer(self, creds: dict, display_name: str, email: str = "", timeout: float = 30.0) -> dict:
        if not str(display_name or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_customer needs a display_name.", retryable=False)
        body: dict[str, Any] = {"DisplayName": display_name}
        if email:
            body["PrimaryEmailAddr"] = {"Address": email}
        return await self._request(creds, "POST", "/customer", "create_customer", body=body, timeout=timeout)

    async def get_customer(self, creds: dict, customer_id: str, timeout: float = 30.0) -> dict:
        if not str(customer_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_customer needs a customer_id.", retryable=False)
        return await self._request(creds, "GET", f"/customer/{customer_id}", "get_customer", timeout=timeout)

    async def create_invoice(self, creds: dict, customer_ref: str, lines: list[dict[str, Any]], timeout: float = 30.0) -> dict:
        if not str(customer_ref or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_invoice needs a customer_ref.", retryable=False)
        if not lines:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_invoice needs lines.", retryable=False)
        return await self._request(creds, "POST", "/invoice", "create_invoice",
                                   body={"CustomerRef": {"value": customer_ref}, "Line": lines}, timeout=timeout)

    async def get_invoice(self, creds: dict, invoice_id: str, timeout: float = 30.0) -> dict:
        if not str(invoice_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_invoice needs an invoice_id.", retryable=False)
        return await self._request(creds, "GET", f"/invoice/{invoice_id}", "get_invoice", timeout=timeout)
