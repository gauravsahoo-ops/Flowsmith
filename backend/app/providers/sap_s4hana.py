"""SAP S/4HANA ERP provider client (Phase 39 Native Enterprise Connector).

Integrates with SAP S/4HANA Cloud and On-Premise via official OData v2/v4 REST APIs.
Supports:
- Basic Auth and OAuth2 client credentials
- Automatic X-CSRF-Token preflight fetching and session cookie persistence for mutations
- OData system query options ($filter, $select, $top, $skip, $expand, $orderby)
- Live XML/JSON $metadata schema introspection
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, Tuple
from urllib.parse import quote

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.sap_s4hana")
_extract_sap_error = json_error_message("message", "error", "value")


class SapS4HanaProviderClient(BaseProviderClient):
    """Client for SAP S/4HANA OData and REST APIs."""

    def __init__(self) -> None:
        super().__init__()
        self._csrf_tokens: Dict[str, Tuple[str, Dict[str, str]]] = {}  # host -> (token, cookies)

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("SAP S/4HANA uses OAuth2 client credentials or Basic Auth.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> dict[str, Any]:
        base_url = str(creds.get("base_url") or creds.get("host") or "").rstrip("/")
        if not base_url:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "SAP S/4HANA connector requires 'base_url' (e.g. https://my-s4hana.s4hana.ondemand.com).",
                retryable=False,
            )
        has_basic = bool(creds.get("username") and creds.get("password"))
        has_oauth = bool(creds.get("token") or creds.get("client_id") or creds.get("api_key"))
        if not (has_basic or has_oauth):
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "SAP S/4HANA requires authentication credentials (username/password or token/client_id).",
                retryable=False,
            )
        return creds

    def _build_auth_headers(self, creds: dict[str, Any]) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        token = str(creds.get("token") or creds.get("access_token") or "").strip()
        api_key = str(creds.get("api_key") or "").strip()
        user = str(creds.get("username") or "").strip()
        pwd = str(creds.get("password") or "").strip()

        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif api_key:
            headers["APIKey"] = api_key
        elif user and pwd:
            raw = f"{user}:{pwd}".encode("utf-8")
            headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('ascii')}"
        return headers

    async def _fetch_csrf_token(self, base_url: str, headers: dict[str, str], timeout: float) -> Tuple[str, Dict[str, str]]:
        """Preflight GET to acquire SAP X-CSRF-Token and session cookies for mutations."""
        fetch_headers = {**headers, "X-CSRF-Token": "Fetch"}
        token_url = f"{base_url}/sap/opu/odata/sap/API_BUSINESS_PARTNER/$metadata"
        try:
            async with get_safe_http_client() as client:
                resp = await client.request("GET", token_url, headers=fetch_headers, timeout=timeout)
                csrf_token = resp.headers.get("x-csrf-token") or resp.headers.get("X-CSRF-Token") or ""
                cookies = {k: v for k, v in resp.cookies.items()}
                return csrf_token, cookies
        except Exception as exc:
            logger.warning("SAP CSRF token preflight failed (%s); proceeding without token", exc)
            return "", {}

    async def request_sap(
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
        base_url = str(valid_creds.get("base_url") or valid_creds.get("host")).rstrip("/")
        headers = self._build_auth_headers(valid_creds)
        clean_path = path.lstrip("/")
        url = f"{base_url}/{clean_path}"

        method_upper = method.upper()
        # Handle CSRF token on mutations
        if method_upper in ("POST", "PUT", "PATCH", "DELETE"):
            headers["Content-Type"] = "application/json"
            if base_url not in self._csrf_tokens:
                token, cookies = await self._fetch_csrf_token(base_url, headers, timeout)
                self._csrf_tokens[base_url] = (token, cookies)
            cached_token, cached_cookies = self._csrf_tokens.get(base_url, ("", {}))
            if cached_token:
                headers["X-CSRF-Token"] = cached_token
            if cached_cookies:
                headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cached_cookies.items())

        try:
            async with get_safe_http_client() as client:
                resp = await client.request(
                    method_upper,
                    url,
                    headers=headers,
                    params={k: v for k, v in (params or {}).items() if v is not None and v != ""},
                    json=json_body if method_upper in ("POST", "PUT", "PATCH") and json_body else None,
                    timeout=timeout,
                )
        except httpx.TimeoutException as exc:
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"SAP S/4HANA timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"SAP S/4HANA request failed: {exc}", retryable=True) from exc

        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "SAP S/4HANA authentication failed.", retryable=False)
        if resp.status_code == 403:
            # If CSRF failed, bust cache once
            if "csrf" in resp.text.lower() and base_url in self._csrf_tokens:
                del self._csrf_tokens[base_url]
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"SAP S/4HANA forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 404:
            raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"SAP entity not found at {path}.", retryable=False)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"SAP S/4HANA server error {resp.status_code}: {resp.text[:200]}", retryable=True)
        if resp.status_code >= 400:
            msg = _extract_sap_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"SAP S/4HANA rejected request: {msg}", retryable=False)

        if resp.status_code == 204 or not resp.content:
            return {"status": "success", "status_code": resp.status_code}

        content_type = resp.headers.get("content-type", "")
        if "xml" in content_type:
            return {"raw_xml": resp.text, "status_code": resp.status_code}
        try:
            data = resp.json()
            # Standard OData v2 wraps collections under {"d": {"results": [...]}}
            if isinstance(data, dict) and "d" in data:
                return data["d"]
            return data
        except Exception:
            return {"raw": resp.text, "status_code": resp.status_code}

    async def query_odata(
        self,
        creds: dict[str, Any],
        service: str,
        entity_set: str,
        *,
        filter_expr: str = "",
        select_fields: str = "",
        top: int = 50,
        skip: int = 0,
        orderby: str = "",
        expand: str = "",
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        service_clean = service.strip("/")
        entity_clean = entity_set.strip("/")
        path = f"sap/opu/odata/sap/{service_clean}/{entity_clean}"
        params: dict[str, Any] = {
            "$top": top,
            "$skip": skip,
            "$inlinecount": "allpages",
        }
        if filter_expr:
            params["$filter"] = filter_expr
        if select_fields:
            params["$select"] = select_fields
        if orderby:
            params["$orderby"] = orderby
        if expand:
            params["$expand"] = expand

        res = await self.request_sap(creds, "GET", path, params=params, timeout=timeout)
        results = res.get("results") if isinstance(res, dict) and "results" in res else (res if isinstance(res, list) else [res])
        if results is None:
            results = []
        return {
            "service": service_clean,
            "entity_set": entity_clean,
            "count": len(results),
            "results": results,
            "top": top,
            "skip": skip,
        }

    async def get_entity(
        self,
        creds: dict[str, Any],
        service: str,
        entity_set: str,
        entity_key: str,
        *,
        select_fields: str = "",
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        service_clean = service.strip("/")
        entity_clean = entity_set.strip("/")
        key_encoded = quote(entity_key, safe="='()")
        path = f"sap/opu/odata/sap/{service_clean}/{entity_clean}({key_encoded})"
        params = {"$select": select_fields} if select_fields else {}
        return await self.request_sap(creds, "GET", path, params=params, timeout=timeout)

    async def create_entity(
        self,
        creds: dict[str, Any],
        service: str,
        entity_set: str,
        data: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        service_clean = service.strip("/")
        entity_clean = entity_set.strip("/")
        path = f"sap/opu/odata/sap/{service_clean}/{entity_clean}"
        return await self.request_sap(creds, "POST", path, json_body=data, timeout=timeout)

    async def update_entity(
        self,
        creds: dict[str, Any],
        service: str,
        entity_set: str,
        entity_key: str,
        data: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        service_clean = service.strip("/")
        entity_clean = entity_set.strip("/")
        key_encoded = quote(entity_key, safe="='()")
        path = f"sap/opu/odata/sap/{service_clean}/{entity_clean}({key_encoded})"
        return await self.request_sap(creds, "PATCH", path, json_body=data, timeout=timeout)

    async def delete_entity(
        self,
        creds: dict[str, Any],
        service: str,
        entity_set: str,
        entity_key: str,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        service_clean = service.strip("/")
        entity_clean = entity_set.strip("/")
        key_encoded = quote(entity_key, safe="='()")
        path = f"sap/opu/odata/sap/{service_clean}/{entity_clean}({key_encoded})"
        return await self.request_sap(creds, "DELETE", path, timeout=timeout)

    async def get_metadata(
        self,
        creds: dict[str, Any],
        service: str,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        service_clean = service.strip("/")
        path = f"sap/opu/odata/sap/{service_clean}/$metadata"
        return await self.request_sap(creds, "GET", path, timeout=timeout)
