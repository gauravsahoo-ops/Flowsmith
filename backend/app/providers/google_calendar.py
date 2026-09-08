"""Google Calendar provider client (Phase 37).

Owns every Google Calendar HTTP concern — the same layering as the
other first-party connectors:

    GoogleCalendar connector (op_execute)
        -> GoogleCalendarProviderClient (this module)
            -> SafeHTTPClient (SSRF-protected, redacted logging)
                -> Google Calendar API v3

Auth: OAuth refresh-token flow ('Connect Google Calendar'). Access
tokens expire (~1 h) and are minted on demand from the encrypted refresh
token, cached in memory only. Client id/secret stay in server settings.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.config import get_settings
from app.security.safe_http_client import get_safe_http_client

GOOGLE_API_BASE = "https://www.googleapis.com"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.@\-]+$")


class GoogleCalendarProviderClient:
    """Low-level Google Calendar v3 client (events)."""

    def __init__(self) -> None:
        self._access_tokens: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        self._access_tokens.clear()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> str:
        refresh_token = str(creds.get("refresh_token") or "").strip()
        if not refresh_token:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Google Calendar connector needs a 'google_calendar' credential — "
                "connect it from the UI ('Connect Google Calendar').",
                retryable=False,
            )
        return refresh_token

    async def _refresh_access_token(self, refresh_token: str) -> tuple[str, float]:
        settings = get_settings()
        client_id = settings.google_client_id
        client_secret = settings.google_client_secret
        if not client_id or not client_secret:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Google OAuth is not configured on the server "
                "(GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET).",
                retryable=False,
            )
        from urllib.parse import urlencode

        body = urlencode({
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        })
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST",
                    "https://oauth2.googleapis.com/token",
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
                "Google rejected the refresh token; reconnect the account.",
                retryable=False,
            )
        try:
            data = response.json()
            token = data["access_token"]
            expires_in = float(data.get("expires_in", 3600))
        except (ValueError, KeyError) as exc:
            raise make_connector_error(
                ConnectorErrorCode.AUTH_FAILED,
                "Google token response malformed.",
                retryable=False,
            ) from exc
        # Refresh 60s early to dodge clock skew.
        return token, time.monotonic() + max(expires_in - 60.0, 30.0)

    async def _access_token(self, refresh_token: str) -> str:
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

    @staticmethod
    def _calendar_id(calendar_id: str) -> str:
        value = str(calendar_id or "primary").strip() or "primary"
        if not _TOKEN_RE.match(value):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "Invalid calendar id.",
                retryable=False,
            )
        return value

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
        self._validate_creds(creds)
        token = await self._access_token(str(creds.get("refresh_token") or "").strip())
        return await self._send(creds, method, path, token, json_body, params, timeout)

    async def _send(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        token: str,
        json_body: Any,
        params: dict[str, Any] | None,
        timeout: float,
        force_refresh: bool = False,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"}
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method,
                    GOOGLE_API_BASE + path,
                    json=json_body or None,
                    params=params or None,
                    headers=headers,
                    timeout=timeout,
                )
        except httpx.TimeoutException as exc:
            raise make_connector_error(
                ConnectorErrorCode.TIMEOUT,
                f"Google Calendar did not respond within {timeout}s.",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"Google Calendar unreachable: {exc}",
                retryable=True,
            ) from exc

        if response.status_code == 401 and not force_refresh:
            refresh_token = str(creds.get("refresh_token") or "").strip()
            self._access_tokens.pop(refresh_token, None)
            fresh = await self._access_token(refresh_token)
            return await self._send(creds, method, path, fresh, json_body, params, timeout, True)
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response, what: str) -> None:
        if response.status_code < 400:
            return
        message = f"Google Calendar {what} failed ({response.status_code})."
        try:
            data = response.json()
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    message = f"{message} {str(err.get('message', ''))[:300]}"
        except ValueError:
            pass
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

    # ------------------------------------------------------------------
    # Events operations (Calendar v3)
    # ------------------------------------------------------------------

    async def list_events(
        self,
        creds: dict[str, Any],
        calendar_id: str,
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 25,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        cal = self._calendar_id(calendar_id)
        params: dict[str, Any] = {"singleEvents": "true", "orderBy": "startTime", "maxResults": max_results}
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        response = await self.request(
            creds, "GET", f"/calendar/v3/calendars/{cal}/events", params=params, timeout=timeout
        )
        self._raise_for_status(response, "list events")
        data = response.json()
        return {"events": data.get("items") or [], "count": len(data.get("items") or []), "calendar_id": cal}

    async def get_event(self, creds: dict[str, Any], calendar_id: str, event_id: str, timeout: float = 30.0) -> dict[str, Any]:
        cal = self._calendar_id(calendar_id)
        response = await self.request(creds, "GET", f"/calendar/v3/calendars/{cal}/events/{event_id}", timeout=timeout)
        self._raise_for_status(response, "get event")
        return {"event": response.json()}

    async def create_event(self, creds: dict[str, Any], calendar_id: str, event: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        cal = self._calendar_id(calendar_id)
        response = await self.request(
            creds, "POST", f"/calendar/v3/calendars/{cal}/events", json_body=event, timeout=timeout
        )
        self._raise_for_status(response, "create event")
        created = response.json()
        return {"id": str(created.get("id", "")), "event": created, "success": True}

    async def update_event(self, creds: dict[str, Any], calendar_id: str, event_id: str, event: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        cal = self._calendar_id(calendar_id)
        response = await self.request(
            creds, "PATCH", f"/calendar/v3/calendars/{cal}/events/{event_id}", json_body=event, timeout=timeout
        )
        self._raise_for_status(response, "update event")
        updated = response.json()
        return {"id": str(updated.get("id", "")), "event": updated, "success": True}

    async def delete_event(self, creds: dict[str, Any], calendar_id: str, event_id: str, timeout: float = 30.0) -> dict[str, Any]:
        cal = self._calendar_id(calendar_id)
        response = await self.request(
            creds, "DELETE", f"/calendar/v3/calendars/{cal}/events/{event_id}", timeout=timeout
        )
        self._raise_for_status(response, "delete event")
        return {"id": event_id, "deleted": True}
