"""HubSpot provider client (Phase 33).

Owns every HubSpot HTTP concern so the connector layer stays a thin
operation mapper — the same layering as Salesforce:

    HubSpot connector (op_execute)
        -> HubSpotProviderClient (this module)
            -> SafeHTTPClient (SSRF-protected, redacted logging)
                -> HubSpot CRM v3 API

Auth: OAuth refresh-token flow ('Connect HubSpot') or a private-app
token. Access tokens expire (~30 min), so they are minted on demand
from the encrypted refresh token and cached in memory only. Client
id/secret come from SERVER settings for OAuth connections and are never
stored in the credential blob.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.config import get_settings
from app.security.safe_http_client import get_safe_http_client

HUBSPOT_API_BASE = "https://api.hubapi.com"

# Standard CRM objects accepted for object_type (v3 API is uniform across
# them; the allowlist stops the object type acting as a path-injection vector).
STANDARD_OBJECTS = frozenset({
    "contacts", "companies", "deals", "tickets", "products", "quotes",
})


class HubSpotProviderClient:
    """Low-level HubSpot REST client (CRM v3)."""

    def __init__(self) -> None:
        self._access_tokens: dict[str, tuple[str, float]] = {}  # refresh_token -> (token, expires_at)
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        self._access_tokens.clear()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> None:
        oauth = bool(creds.get("oauth")) or bool(creds.get("refresh_token"))
        private = bool(str(creds.get("private_token") or "").strip())
        if not oauth and not private:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "HubSpot connector needs a 'hubspot' credential - connect it from the UI "
                "('Connect HubSpot') or provide a private_token.",
                retryable=False,
            )

    async def _refresh_access_token(self, refresh_token: str) -> tuple[str, float]:
        """Exchange the refresh token for an access token (server config).

        Returns (access_token, expires_at_epoch).
        """
        settings = get_settings()
        client_id = settings.hubspot_client_id
        client_secret = settings.hubspot_client_secret
        if not client_id or not client_secret:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "HubSpot OAuth is not configured on the server "
                "(HUBSPOT_CLIENT_ID/HUBSPOT_CLIENT_SECRET); use a private_token instead.",
                retryable=False,
            )
        body = (
            f"grant_type=refresh_token&client_id={client_id}"
            f"&client_secret={client_secret}&refresh_token={refresh_token}"
        )
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST",
                    f"{HUBSPOT_API_BASE}/oauth/v1/token",
                    data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=30.0,
                )
        except httpx.TimeoutException as exc:
            raise make_connector_error(
                ConnectorErrorCode.TIMEOUT,
                "The token endpoint did not respond in time.",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"Token endpoint unreachable: {exc}",
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            raise make_connector_error(
                ConnectorErrorCode.AUTH_FAILED,
                "HubSpot rejected the refresh token; reconnect the account.",
                retryable=False,
            )
        try:
            data = response.json()
            token = data["access_token"]
            expires_in = float(data.get("expires_in", 1800))
        except (ValueError, KeyError) as exc:
            raise make_connector_error(
                ConnectorErrorCode.AUTH_FAILED,
                "HubSpot token response malformed.",
                retryable=False,
            ) from exc
        # Refresh 60s early to dodge clock skew.
        return token, time.monotonic() + max(expires_in - 60.0, 30.0)

    async def _access_token(self, creds: dict[str, Any]) -> str:
        private = str(creds.get("private_token") or "").strip()
        if private and not creds.get("oauth"):
            return private
        refresh_token = str(creds.get("refresh_token") or "").strip()
        if not refresh_token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "HubSpot credential has no refresh_token/private_token.",
                retryable=False,
            )
        async with self._lock:
            cached = self._access_tokens.get(refresh_token)
            if cached and cached[1] > time.monotonic():
                return cached[0]
            token, expires_at = await self._refresh_access_token(refresh_token)
            self._access_tokens[refresh_token] = (token, expires_at)
            return token

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    async def request(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> httpx.Response:
        """One authenticated API call; retries once on an auth failure by
        forcing a token refresh (401 after refresh => AUTH_FAILED)."""
        self._validate_creds(creds)
        token = await self._access_token(creds)
        force_refresh = False
        return await self._send(
            creds, method, path, token, json_body, params, timeout, force_refresh
        )

    async def _send(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        token: str,
        json_body: Any,
        params: dict[str, Any] | None,
        timeout: float,
        force_refresh: bool,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"}
        url = f"{HUBSPOT_API_BASE}{path}"
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, url, json=json_body or None, params=params or None,
                    headers=headers, timeout=timeout,
                )
        except httpx.TimeoutException as exc:
            raise make_connector_error(
                ConnectorErrorCode.TIMEOUT,
                f"HubSpot did not respond within {timeout}s.",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"HubSpot unreachable: {exc}",
                retryable=True,
            ) from exc

        if response.status_code == 401 and not force_refresh:
            # Access token expired/revoked mid-flight: refresh once.
            refresh_token = str(creds.get("refresh_token") or "").strip()
            self._access_tokens.pop(refresh_token, None)
            fresh = await self._access_token(creds)
            return await self._send(
                creds, method, path, fresh, json_body, params, timeout, True
            )
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response, what: str) -> Any:
        if response.status_code < 400:
            return None
        message = f"HubSpot {what} failed ({response.status_code})."
        detail = ""
        try:
            data = response.json()
            if isinstance(data, dict):
                # v3 error shape: {"category": ..., "message": ...}
                detail = str(data.get("message") or "")
        except ValueError:
            pass
        if detail:
            message = f"{message} {detail[:300]}"

        code = ConnectorErrorCode.BAD_REQUEST
        retryable = False
        if response.status_code == 401:
            code = ConnectorErrorCode.AUTH_FAILED
        elif response.status_code == 403:
            code = ConnectorErrorCode.FORBIDDEN
        elif response.status_code == 404:
            code = ConnectorErrorCode.NOT_FOUND
        elif response.status_code == 429:
            code = ConnectorErrorCode.RATE_LIMITED
            retryable = True
        elif response.status_code >= 500:
            code = ConnectorErrorCode.UNAVAILABLE
            retryable = True
        raise make_connector_error(code, message, retryable=retryable)

    @staticmethod
    def _object_type(object_type: str) -> str:
        value = str(object_type or "").strip().lower()
        if value not in STANDARD_OBJECTS:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Unsupported HubSpot object_type '{object_type}' "
                f"(use one of: {', '.join(sorted(STANDARD_OBJECTS))}).",
                retryable=False,
            )
        return value

    # ------------------------------------------------------------------
    # Operations (CRM v3 is uniform across standard objects)
    # ------------------------------------------------------------------

    async def search_records(
        self,
        creds: dict[str, Any],
        object_type: str,
        search_field: str,
        search_value: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Find records whose property equals the value (search endpoint)."""
        ot = self._object_type(object_type)
        response = await self.request(
            creds, "POST", f"/crm/v3/objects/{ot}/search",
            json_body={
                "filterGroups": [{
                    "filters": [{
                        "propertyName": search_field,
                        "operator": "EQ",
                        "value": search_value,
                    }],
                }],
                "limit": 2,
            },
            timeout=timeout,
        )
        self._raise_for_status(response, "search")
        try:
            data = response.json()
            results = data.get("results") or []
        except ValueError as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "HubSpot search returned malformed JSON.",
                retryable=False,
            ) from exc
        record = results[0] if results else None
        return {
            "found": record is not None,
            "record": record,
            "object_type": ot,
            "search_field": search_field,
            "total": len(results),
        }

    async def get_record(self, creds: dict[str, Any], object_type: str, record_id: str, timeout: float = 30.0) -> dict[str, Any]:
        ot = self._object_type(object_type)
        response = await self.request(
            creds, "GET", f"/crm/v3/objects/{ot}/{record_id}", timeout=timeout
        )
        self._raise_for_status(response, "get")
        return {"record": response.json()}

    async def create_record(self, creds: dict[str, Any], object_type: str, properties: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        ot = self._object_type(object_type)
        response = await self.request(
            creds, "POST", f"/crm/v3/objects/{ot}",
            json_body={"properties": properties}, timeout=timeout,
        )
        self._raise_for_status(response, "create")
        record = response.json()
        return {"id": str(record.get("id", "")), "record": record, "success": True}

    async def update_record(self, creds: dict[str, Any], object_type: str, record_id: str, properties: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        ot = self._object_type(object_type)
        response = await self.request(
            creds, "PATCH", f"/crm/v3/objects/{ot}/{record_id}",
            json_body={"properties": properties}, timeout=timeout,
        )
        self._raise_for_status(response, "update")
        record = response.json()
        return {"id": str(record.get("id", "")), "record": record, "success": True}
