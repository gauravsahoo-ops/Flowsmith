"""Calendly provider client (Batch B, original implementation).

Personal-access-token Bearer auth. Ops: list event types, list events,
get event, cancel event. 429/5xx retryable.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

CALENDLY_API_BASE = "https://api.calendly.com"


def _token(creds: dict) -> str:
    token = str((creds or {}).get("access_token") or "").strip()
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Calendly connector needs a 'calendly' credential with access_token.",
            retryable=False,
        )
    return token


def _raise(status: int, body: str, what: str) -> None:
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Calendly auth failed during {what}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Calendly forbade {what}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Calendly resource missing during {what}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Calendly rate limited during {what}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Calendly unavailable during {what}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Calendly rejected {what}: {body[:200]}", retryable=False)


class CalendlyProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (users/me)."""
        data = await self._get(creds, "/users/me", None, "test connection")
        resource = data.get("resource", {}) if isinstance(data, dict) else {}
        email = resource.get("email", "") if isinstance(resource, dict) else ""
        return {"ok": True, "message": f"Connected as {email}." if email else "Connected."}

    async def _get(self, creds: dict, path: str, params: dict[str, Any] | None, what: str, timeout: float = 30.0) -> dict:
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "GET", f"{CALENDLY_API_BASE}{path}",
                    headers={"Authorization": f"Bearer {_token(creds)}"},
                    params=params or {}, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Calendly unreachable during {what}: {exc}", retryable=True,
            ) from exc
        _raise(response.status_code, response.text, what)
        try:
            data = response.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    async def _post(self, creds: dict, path: str, what: str, timeout: float = 30.0) -> dict:
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST", f"{CALENDLY_API_BASE}{path}",
                    headers={"Authorization": f"Bearer {_token(creds)}"},
                    timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Calendly unreachable during {what}: {exc}", retryable=True,
            ) from exc
        _raise(response.status_code, response.text, what)
        try:
            data = response.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    async def list_event_types(self, creds: dict, user_uri: str = "", timeout: float = 30.0) -> list:
        params = {"user": user_uri.strip()} if str(user_uri or "").strip() else {}
        data = await self._get(creds, "/event_types", params, "list event types", timeout)
        items = data.get("collection", [])
        return items if isinstance(items, list) else []

    async def list_events(self, creds: dict, user_uri: str = "", count: int = 20, timeout: float = 30.0) -> list:
        params: dict[str, Any] = {"count": max(1, min(count, 100))}
        if str(user_uri or "").strip():
            params["user"] = user_uri.strip()
        data = await self._get(creds, "/scheduled_events", params, "list events", timeout)
        items = data.get("collection", [])
        return items if isinstance(items, list) else []

    async def get_event(self, creds: dict, event_uuid: str, timeout: float = 30.0) -> dict:
        if not str(event_uuid or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_event needs an event uuid.", retryable=False)
        data = await self._get(creds, f"/scheduled_events/{event_uuid.strip()}", None, "get event", timeout)
        resource = data.get("resource", {})
        return resource if isinstance(resource, dict) else {}

    async def cancel_event(self, creds: dict, event_uuid: str, timeout: float = 30.0) -> dict:
        if not str(event_uuid or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "cancel_event needs an event uuid.", retryable=False)
        data = await self._post(creds, f"/scheduled_events/{event_uuid.strip()}/cancellation", "cancel event", timeout)
        return {"cancelled": True, "event": event_uuid.strip(), **data}
