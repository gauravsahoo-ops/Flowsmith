"""Oracle NetSuite ERP provider client (Phase 39 Native Enterprise Connector).

Integrates with NetSuite SuiteTalk REST Web Services and SuiteQL.
Supports:
- Token-Based Auth (TBA OAuth 1.0a HMAC-SHA256) and OAuth 2.0 Bearer tokens
- SuiteQL query execution (SELECT ... FROM customer / salesOrder / transaction)
- Record operations for standard and custom NetSuite record types
- Metadata schema introspection for record types
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from typing import Any
from urllib.parse import quote

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.netsuite")
_extract_netsuite_error = json_error_message("o:errorDetails", "title", "message", "detail")


class NetSuiteProviderClient(BaseProviderClient):
    """Client for Oracle NetSuite SuiteTalk REST APIs."""

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("NetSuite TBA tokens do not expire; OAuth2 tokens use standard token endpoint.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> dict[str, Any]:
        account_id = str(creds.get("account_id") or creds.get("realm") or "").strip()
        if not account_id:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "NetSuite connector requires 'account_id' (e.g. 1234567 or TSTDRV1234567).",
                retryable=False,
            )
        has_token = bool(creds.get("token") or creds.get("access_token"))
        has_tba = bool(
            creds.get("consumer_key") and creds.get("consumer_secret")
            and creds.get("token_id") and creds.get("token_secret")
        )
        if not (has_token or has_tba):
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "NetSuite requires OAuth 2.0 token or TBA credentials (consumer_key/secret, token_id/secret).",
                retryable=False,
            )
        return creds

    def _build_auth_header(self, creds: dict[str, Any], method: str, url: str) -> str:
        token = str(creds.get("token") or creds.get("access_token") or "").strip()
        if token:
            return f"Bearer {token}"

        # Generate OAuth 1.0a TBA Header
        account_id = str(creds.get("account_id") or creds.get("realm")).upper().replace("-", "_")
        consumer_key = str(creds.get("consumer_key")).strip()
        consumer_secret = str(creds.get("consumer_secret")).strip()
        token_id = str(creds.get("token_id")).strip()
        token_secret = str(creds.get("token_secret")).strip()

        nonce = secrets.token_hex(16)
        timestamp = str(int(time.time()))

        base_string = "&".join([
            method.upper(),
            quote(url.split("?")[0], safe=""),
            quote(f"oauth_consumer_key={consumer_key}&oauth_nonce={nonce}&oauth_signature_method=HMAC-SHA256&oauth_timestamp={timestamp}&oauth_token={token_id}&oauth_version=1.0", safe="")
        ])
        key = f"{quote(consumer_secret, safe='')}&{quote(token_secret, safe='')}".encode("utf-8")
        signature = base64.b64encode(hmac.new(key, base_string.encode("utf-8"), hashlib.sha256).digest()).decode("ascii")

        return (
            f'OAuth realm="{account_id}", '
            f'oauth_consumer_key="{consumer_key}", '
            f'oauth_token="{token_id}", '
            f'oauth_signature_method="HMAC-SHA256", '
            f'oauth_timestamp="{timestamp}", '
            f'oauth_nonce="{nonce}", '
            f'oauth_version="1.0", '
            f'oauth_signature="{quote(signature, safe="")}"'
        )

    async def request_netsuite(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        valid_creds = self._validate_creds(creds)
        raw_account = str(valid_creds.get("account_id") or valid_creds.get("realm")).lower().replace("_", "-")
        # NetSuite REST Web Services endpoint: https://<account_id>.suitetalk.api.netsuite.com/services/rest/<path>
        base_url = f"https://{raw_account}.suitetalk.api.netsuite.com/services/rest"
        clean_path = path.lstrip("/")
        url = f"{base_url}/{clean_path}"

        method_upper = method.upper()
        auth_header = self._build_auth_header(valid_creds, method_upper, url)
        headers = {
            "Accept": "application/json",
            "Authorization": auth_header,
        }
        if method_upper in ("POST", "PUT", "PATCH"):
            headers["Content-Type"] = "application/json"

        try:
            async with get_safe_http_client() as client:
                resp = await client.request(
                    method_upper,
                    url,
                    headers=headers,
                    params={k: v for k, v in (params or {}).items() if v is not None and v != ""},
                    json=json_body if json_body and method_upper in ("POST", "PUT", "PATCH") else None,
                    timeout=timeout,
                )
        except httpx.TimeoutException as exc:
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"NetSuite request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"NetSuite connection failed: {exc}", retryable=True) from exc

        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "NetSuite authorization failed; verify TBA or OAuth credentials.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"NetSuite permission denied: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"NetSuite record not found at {path}.", retryable=False)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"NetSuite server error {resp.status_code}: {resp.text[:200]}", retryable=True)
        if resp.status_code >= 400:
            msg = _extract_netsuite_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"NetSuite API error: {msg}", retryable=False)

        if resp.status_code == 204 or not resp.content:
            return {"status": "success", "status_code": resp.status_code}

        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text, "status_code": resp.status_code}

    async def query_suiteql(
        self,
        creds: dict[str, Any],
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Execute a SuiteQL query against NetSuite records."""
        path = "query/v1/suiteql"
        params = {"limit": limit, "offset": offset}
        body = {"q": query}
        res = await self.request_netsuite(creds, "POST", path, params=params, json_body=body, timeout=timeout)
        items = res.get("items") if isinstance(res, dict) and "items" in res else ([res] if isinstance(res, dict) else [])
        if items is None:
            items = []
        total = res.get("totalResults", len(items)) if isinstance(res, dict) else len(items)
        return {
            "query": query,
            "total_results": total,
            "count": len(items),
            "items": items,
            "has_more": res.get("hasMore", False) if isinstance(res, dict) else False,
            "limit": limit,
            "offset": offset,
        }

    async def list_records(
        self,
        creds: dict[str, Any],
        record_type: str,
        *,
        q: str = "",
        limit: int = 50,
        offset: int = 0,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        rtype = quote(record_type.strip(), safe="")
        path = f"record/v1/{rtype}"
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if q:
            params["q"] = q
        res = await self.request_netsuite(creds, "GET", path, params=params, timeout=timeout)
        items = res.get("items") if isinstance(res, dict) and "items" in res else ([res] if isinstance(res, dict) else [])
        if items is None:
            items = []
        return {
            "record_type": record_type,
            "count": len(items),
            "total": res.get("totalResults", len(items)) if isinstance(res, dict) else len(items),
            "items": items,
            "limit": limit,
            "offset": offset,
        }

    async def get_record(
        self,
        creds: dict[str, Any],
        record_type: str,
        record_id: str,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        rtype = quote(record_type.strip(), safe="")
        rid = quote(record_id.strip(), safe="")
        path = f"record/v1/{rtype}/{rid}"
        return await self.request_netsuite(creds, "GET", path, timeout=timeout)

    async def create_record(
        self,
        creds: dict[str, Any],
        record_type: str,
        data: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        rtype = quote(record_type.strip(), safe="")
        path = f"record/v1/{rtype}"
        return await self.request_netsuite(creds, "POST", path, json_body=data, timeout=timeout)

    async def update_record(
        self,
        creds: dict[str, Any],
        record_type: str,
        record_id: str,
        data: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        rtype = quote(record_type.strip(), safe="")
        rid = quote(record_id.strip(), safe="")
        path = f"record/v1/{rtype}/{rid}"
        return await self.request_netsuite(creds, "PATCH", path, json_body=data, timeout=timeout)

    async def delete_record(
        self,
        creds: dict[str, Any],
        record_type: str,
        record_id: str,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        rtype = quote(record_type.strip(), safe="")
        rid = quote(record_id.strip(), safe="")
        path = f"record/v1/{rtype}/{rid}"
        return await self.request_netsuite(creds, "DELETE", path, timeout=timeout)

    async def get_metadata(
        self,
        creds: dict[str, Any],
        record_type: str,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        rtype = quote(record_type.strip(), safe="")
        path = f"record/v1/metadata-catalog/{rtype}"
        return await self.request_netsuite(creds, "GET", path, timeout=timeout)
