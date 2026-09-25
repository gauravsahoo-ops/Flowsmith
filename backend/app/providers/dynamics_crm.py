"""Microsoft Dynamics 365 / Dataverse Provider Client.

Owns Dataverse Web API v9.2 HTTP concerns (SSRF protection, authentication
token exchange and caching, OData query building, FetchXML, and error translation):

    DynamicsCrmConnector (op_execute)
        -> DynamicsCrmProviderClient (this module)
            -> SafeHTTPClient (SSRF-protected, redacted logging)
                -> Microsoft Dataverse Web API v9.2

Auth:
    1. OAuth2 refresh-token flow ("Connect Microsoft Dynamics 365"):
       User authorizes via Azure Entra ID; tokens are refreshed server-side.
    2. Server-to-Server (Client Credentials / Service Principal):
       Uses Azure App Registration client_id, client_secret, and tenant_id
       with scope {instance_url}/.default.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.config import get_settings
from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger(__name__)

# Standard entity names mapped to their canonical EntitySet names.
# Custom entities (e.g. 'new_project') are preserved or auto-pluralized.
STANDARD_ENTITY_SETS: dict[str, str] = {
    "account": "accounts",
    "accounts": "accounts",
    "contact": "contacts",
    "contacts": "contacts",
    "lead": "leads",
    "leads": "leads",
    "opportunity": "opportunities",
    "opportunities": "opportunities",
    "incident": "incidents",
    "incidents": "incidents",
    "case": "incidents",
    "cases": "incidents",
    "task": "tasks",
    "tasks": "tasks",
    "systemuser": "systemusers",
    "systemusers": "systemusers",
    "user": "systemusers",
    "users": "systemusers",
    "phonecall": "phonecalls",
    "phonecalls": "phonecalls",
    "email": "emails",
    "emails": "emails",
    "appointment": "appointments",
    "appointments": "appointments",
}


def normalize_entity_set(name: str) -> str:
    """Normalize entity logical name or entity set name into its plural EntitySet identifier."""
    cleaned = (name or "").strip().lower()
    if not cleaned:
        return "accounts"
    if cleaned in STANDARD_ENTITY_SETS:
        return STANDARD_ENTITY_SETS[cleaned]
    # If it ends with 's', return as-is
    if cleaned.endswith("s"):
        return cleaned
    # Basic English pluralization fallback
    if cleaned.endswith("y") and not cleaned.endswith(("ay", "ey", "oy", "uy")):
        return f"{cleaned[:-1]}ies"
    return f"{cleaned}s"


def clean_guid(val: Any) -> str:
    """Strip braces and whitespace from a GUID string."""
    s = str(val or "").strip()
    match = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", s)
    if match:
        return match.group(0).lower()
    return s.strip("{}'\"")


class DynamicsCrmProviderClient:
    """Low-level Microsoft Dynamics 365 / Dataverse REST client (Web API v9.2)."""

    def __init__(self) -> None:
        self._access_tokens: dict[str, tuple[str, float]] = {}  # cache_key -> (token, expires_at_monotonic)
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        """Clear cached tokens (useful in tests)."""
        self._access_tokens.clear()

    # ------------------------------------------------------------------
    # Authentication & Token Resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> str:
        instance_url = str(creds.get("instance_url") or "").strip().rstrip("/")
        if not instance_url:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Microsoft Dynamics 365 credential requires an instance_url (e.g. 'https://myorg.crm.dynamics.com').",
                retryable=False,
            )
        auth_type = str(creds.get("auth_type") or "oauth2").lower()
        has_oauth = bool(creds.get("refresh_token") or creds.get("oauth") or creds.get("access_token"))
        has_s2s = bool(str(creds.get("client_id") or "").strip() and str(creds.get("client_secret") or "").strip())
        if auth_type == "client_credentials" and not has_s2s:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Client credentials auth requires both client_id and client_secret.",
                retryable=False,
            )
        if not has_oauth and not has_s2s:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Microsoft Dynamics 365 connector requires an authorized OAuth connection or S2S client credentials.",
                retryable=False,
            )
        return instance_url

    async def _get_client_credentials_token(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        instance_url: str,
    ) -> tuple[str, float]:
        """Mint a token via Azure AD Client Credentials grant."""
        token_url = f"https://login.microsoftonline.com/{tenant_id or 'common'}/oauth2/v2.0/token"
        body = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": f"{instance_url}/.default",
        }
        try:
            async with get_safe_http_client() as client:
                resp = await client.request(
                    "POST",
                    token_url,
                    data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Accept-Encoding": "identity"},
                    timeout=20.0,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"Azure AD token endpoint unreachable: {exc}",
                retryable=True,
            ) from exc

        if resp.status_code >= 400:
            error_desc = "Authentication failed"
            try:
                error_desc = resp.json().get("error_description", resp.text)
            except Exception:
                pass
            raise make_connector_error(
                ConnectorErrorCode.AUTH_FAILED,
                f"Azure AD rejected client credentials: {error_desc}",
                retryable=False,
            )

        data = resp.json()
        token = data["access_token"]
        expires_in = float(data.get("expires_in", 3600))
        return token, time.monotonic() + max(expires_in - 60.0, 30.0)

    async def _refresh_oauth_token(
        self,
        tenant_id: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
    ) -> tuple[str, float]:
        """Exchange an OAuth refresh token for an access token."""
        settings = get_settings()
        cid = client_id or getattr(settings, "dynamics_crm_client_id", "")
        csec = client_secret or getattr(settings, "dynamics_crm_client_secret", "")
        token_url = f"https://login.microsoftonline.com/{tenant_id or 'common'}/oauth2/v2.0/token"

        body = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": cid,
        }
        if csec:
            body["client_secret"] = csec

        try:
            async with get_safe_http_client() as client:
                resp = await client.request(
                    "POST",
                    token_url,
                    data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Accept-Encoding": "identity"},
                    timeout=20.0,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"Azure AD token endpoint unreachable: {exc}",
                retryable=True,
            ) from exc

        if resp.status_code >= 400:
            raise make_connector_error(
                ConnectorErrorCode.AUTH_FAILED,
                "Microsoft Dynamics 365 rejected the refresh token. Reconnect the account.",
                retryable=False,
            )

        data = resp.json()
        token = data["access_token"]
        expires_in = float(data.get("expires_in", 3600))
        return token, time.monotonic() + max(expires_in - 60.0, 30.0)

    async def _access_token(self, creds: dict[str, Any], instance_url: str) -> str:
        """Resolve and cache a valid Bearer access token."""
        auth_type = str(creds.get("auth_type") or "oauth2").lower()
        tenant_id = str(creds.get("tenant_id") or "common").strip()
        client_id = str(creds.get("client_id") or "").strip()
        client_secret = str(creds.get("client_secret") or "").strip()
        refresh_token = str(creds.get("refresh_token") or "").strip()
        # 0. Fast-path: if caller already has a valid, unexpired access_token, reuse immediately
        static_token = str(creds.get("access_token") or "").strip()
        expires_at = float(creds.get("expires_at") or 0)
        if static_token and expires_at > time.time() + 60.0:
            return static_token

        # 1. Server-to-server client credentials
        if auth_type == "client_credentials" or (not refresh_token and client_id and client_secret):
            cache_key = f"s2s:{tenant_id}:{client_id}:{instance_url}"
            async with self._lock:
                cached = self._access_tokens.get(cache_key)
                if cached and cached[1] > time.monotonic():
                    return cached[0]
                token, exp = await self._get_client_credentials_token(
                    tenant_id, client_id, client_secret, instance_url
                )
                self._access_tokens[cache_key] = (token, exp)
                return token

        # 2. OAuth refresh token flow
        if refresh_token:
            cache_key = f"oauth:{refresh_token}"
            async with self._lock:
                cached = self._access_tokens.get(cache_key)
                if cached and cached[1] > time.monotonic():
                    return cached[0]
                token, exp = await self._refresh_oauth_token(
                    tenant_id, refresh_token, client_id, client_secret
                )
                self._access_tokens[cache_key] = (token, exp)
                return token

        # 3. Static access token fallback
        if static_token:
            return static_token

        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Dynamics 365 credential lacks valid authentication tokens or credentials.",
            retryable=False,
        )

    # ------------------------------------------------------------------
    # HTTP Request & Error Normalization
    # ------------------------------------------------------------------

    async def request(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> httpx.Response:
        """Execute an authenticated call against Dataverse Web API v9.2."""
        instance_url = self._validate_creds(creds)
        token = await self._access_token(creds, instance_url)

        req_headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Encoding": "identity",
        }
        if method.upper() in ("POST", "PATCH", "PUT"):
            req_headers["Prefer"] = "return=representation"
        if headers:
            req_headers.update(headers)

        clean_path = path if path.startswith("/") else f"/{path}"
        url = f"{instance_url}{clean_path}"

        try:
            async with get_safe_http_client() as client:
                resp = await client.request(
                    method.upper(),
                    url,
                    json=json_body if json_body is not None else None,
                    headers=req_headers,
                    timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"Dynamics 365 endpoint unreachable: {exc}",
                retryable=True,
            ) from exc

        # Handle specific error status codes
        if resp.status_code >= 400:
            error_code = ConnectorErrorCode.PROVIDER_ERROR
            retryable = False
            retry_after: float | None = None

            if resp.status_code in (401, 403):
                error_code = ConnectorErrorCode.AUTH_FAILED
            elif resp.status_code == 404:
                error_code = ConnectorErrorCode.NOT_FOUND
            elif resp.status_code == 429:
                error_code = ConnectorErrorCode.RATE_LIMITED
                retryable = True
                try:
                    retry_after = float(resp.headers.get("Retry-After", 5.0))
                except Exception:
                    retry_after = 5.0
            elif resp.status_code in (400, 422):
                error_code = ConnectorErrorCode.VALIDATION_ERROR

            # Extract Dataverse error message
            msg = f"Dynamics 365 error (HTTP {resp.status_code})"
            try:
                err_data = resp.json().get("error", {})
                if isinstance(err_data, dict):
                    msg = err_data.get("message") or msg
            except Exception:
                pass

            raise make_connector_error(
                error_code,
                msg,
                retryable=retryable,
                retry_after=retry_after,
            )

        return resp

    # ------------------------------------------------------------------
    # High-Level Dataverse Web API v9.2 Operations
    # ------------------------------------------------------------------

    async def who_am_i(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Verify connection and retrieve User, BusinessUnit, and Organization GUIDs."""
        resp = await self.request(creds, "GET", "/api/data/v9.2/WhoAmI")
        return resp.json()

    async def query(
        self,
        creds: dict[str, Any],
        entity_set: str,
        *,
        filter_expr: str = "",
        select: str | list[str] = "",
        expand: str = "",
        orderby: str = "",
        top: int = 0,
        fetch_xml: str = "",
    ) -> list[dict[str, Any]]:
        """Query Dataverse records using OData system query options or FetchXML."""
        canonical_set = normalize_entity_set(entity_set)

        if fetch_xml and fetch_xml.strip():
            encoded_xml = quote(fetch_xml.strip())
            path = f"/api/data/v9.2/{canonical_set}?fetchXml={encoded_xml}"
            resp = await self.request(creds, "GET", path)
            return resp.json().get("value", [])

        params: dict[str, str] = {}
        if filter_expr.strip():
            params["$filter"] = filter_expr.strip()
        if select:
            params["$select"] = ",".join(select) if isinstance(select, list) else select.strip()
        if expand.strip():
            params["$expand"] = expand.strip()
        if orderby.strip():
            params["$orderby"] = orderby.strip()
        if top and int(top) > 0:
            params["$top"] = str(int(top))

        query_str = f"?{urlencode(params)}" if params else ""
        path = f"/api/data/v9.2/{canonical_set}{query_str}"
        resp = await self.request(creds, "GET", path)
        data = resp.json()
        records = list(data.get("value", []))
        next_link = data.get("@odata.nextLink")

        target_top = int(top) if top and int(top) > 0 else 0
        max_pages = 10
        page = 1

        while next_link and page < max_pages:
            if target_top and len(records) >= target_top:
                break
            page += 1
            instance_url = self._validate_creds(creds)
            clean_next = next_link.replace(instance_url, "")
            next_resp = await self.request(creds, "GET", clean_next)
            next_data = next_resp.json()
            page_records = next_data.get("value", [])
            if not page_records:
                break
            records.extend(page_records)
            next_link = next_data.get("@odata.nextLink")

        if target_top and len(records) > target_top:
            records = records[:target_top]
        return records

    async def get_record(
        self,
        creds: dict[str, Any],
        entity_set: str,
        record_id: str,
        *,
        select: str | list[str] = "",
        expand: str = "",
    ) -> dict[str, Any]:
        """Fetch a single record by entity and GUID."""
        canonical_set = normalize_entity_set(entity_set)
        guid = clean_guid(record_id)
        if not guid:
            raise make_connector_error(
                ConnectorErrorCode.VALIDATION_ERROR,
                "Dynamics 365 get operation requires a valid record_id (GUID).",
                retryable=False,
            )

        params: dict[str, str] = {}
        if select:
            params["$select"] = ",".join(select) if isinstance(select, list) else select.strip()
        if expand.strip():
            params["$expand"] = expand.strip()

        query_str = f"?{urlencode(params)}" if params else ""
        path = f"/api/data/v9.2/{canonical_set}({guid}){query_str}"
        resp = await self.request(creds, "GET", path)
        return resp.json()

    async def create_record(
        self,
        creds: dict[str, Any],
        entity_set: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new record in Dataverse."""
        canonical_set = normalize_entity_set(entity_set)
        if not data or not isinstance(data, dict):
            raise make_connector_error(
                ConnectorErrorCode.VALIDATION_ERROR,
                "Dynamics 365 create operation requires record data.",
                retryable=False,
            )

        path = f"/api/data/v9.2/{canonical_set}"
        resp = await self.request(creds, "POST", path, json_body=data)
        if resp.status_code == 201 or resp.text:
            try:
                return resp.json()
            except Exception:
                pass

        # Parse ID from OData-EntityId header if body is empty
        entity_id_header = resp.headers.get("OData-EntityId", "")
        created_id = clean_guid(entity_id_header)
        return {"id": created_id, "entity_set": canonical_set, "created": True}

    async def update_record(
        self,
        creds: dict[str, Any],
        entity_set: str,
        record_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Update an existing record in Dataverse by GUID."""
        canonical_set = normalize_entity_set(entity_set)
        guid = clean_guid(record_id)
        if not guid:
            raise make_connector_error(
                ConnectorErrorCode.VALIDATION_ERROR,
                "Dynamics 365 update operation requires a valid record_id (GUID).",
                retryable=False,
            )
        if not data or not isinstance(data, dict):
            raise make_connector_error(
                ConnectorErrorCode.VALIDATION_ERROR,
                "Dynamics 365 update operation requires record data to apply.",
                retryable=False,
            )

        path = f"/api/data/v9.2/{canonical_set}({guid})"
        headers = {"If-Match": "*"}
        resp = await self.request(creds, "PATCH", path, json_body=data, headers=headers)
        if resp.text:
            try:
                return resp.json()
            except Exception:
                pass
        return {"id": guid, "entity_set": canonical_set, "updated": True}

    async def upsert_record(
        self,
        creds: dict[str, Any],
        entity_set: str,
        key_field: str,
        key_value: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Upsert a record using an alternate key."""
        canonical_set = normalize_entity_set(entity_set)
        k_field = (key_field or "").strip()
        k_val = (key_value or "").strip()
        if not k_field or not k_val:
            raise make_connector_error(
                ConnectorErrorCode.VALIDATION_ERROR,
                "Dynamics 365 upsert operation requires key_field and key_value.",
                retryable=False,
            )

        # Alternate key format: /entitySet(keyName='keyValue')
        encoded_val = quote(k_val)
        path = f"/api/data/v9.2/{canonical_set}({k_field}='{encoded_val}')"
        resp = await self.request(creds, "PATCH", path, json_body=data)
        if resp.text:
            try:
                return resp.json()
            except Exception:
                pass
        return {"key_field": k_field, "key_value": k_val, "upserted": True}

    async def delete_record(
        self,
        creds: dict[str, Any],
        entity_set: str,
        record_id: str,
    ) -> dict[str, Any]:
        """Delete a record by GUID."""
        canonical_set = normalize_entity_set(entity_set)
        guid = clean_guid(record_id)
        if not guid:
            raise make_connector_error(
                ConnectorErrorCode.VALIDATION_ERROR,
                "Dynamics 365 delete operation requires a valid record_id (GUID).",
                retryable=False,
            )

        path = f"/api/data/v9.2/{canonical_set}({guid})"
        await self.request(creds, "DELETE", path)
        return {"id": guid, "entity_set": canonical_set, "deleted": True}

    async def execute_action(
        self,
        creds: dict[str, Any],
        action_name: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a custom or unbound Dataverse action."""
        act = (action_name or "").strip().lstrip("/")
        if not act:
            raise make_connector_error(
                ConnectorErrorCode.VALIDATION_ERROR,
                "Dynamics 365 execute_action requires an action_name.",
                retryable=False,
            )

        path = f"/api/data/v9.2/{act}"
        resp = await self.request(creds, "POST", path, json_body=payload or {})
        if resp.text:
            try:
                return resp.json()
            except Exception:
                pass
        return {"action": act, "status": "executed"}
