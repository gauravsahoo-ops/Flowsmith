"""Zoom provider client (Batch B, original implementation).

Bearer access-token auth (Server-to-Server OAuth token stored as the
credential). Ops: list user meetings, get meeting, create meeting,
delete meeting. 429/5xx retryable.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

ZOOM_API_BASE = "https://api.zoom.us/v2"


def _token(creds: dict) -> str:
    token = str((creds or {}).get("access_token") or "").strip()
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Zoom connector needs a 'zoom' credential with access_token.",
            retryable=False,
        )
    return token


def _raise(status: int, body: str, what: str) -> None:
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Zoom auth failed during {what}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Zoom forbade {what}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Zoom resource missing during {what}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Zoom rate limited during {what}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Zoom unavailable during {what}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Zoom rejected {what}: {body[:200]}", retryable=False)


class ZoomProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (users/me)."""
        data = await self._request("GET", "/users/me", creds, what="test connection")
        email = data.get("email", "") if isinstance(data, dict) else ""
        return {"ok": True, "message": f"Connected as {email}." if email else "Connected."}

    async def _request(
        self, method: str, path: str, creds: dict, *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 30.0, what: str,
    ) -> Any:
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{ZOOM_API_BASE}{path}",
                    headers={"Authorization": f"Bearer {_token(creds)}", "Content-Type": "application/json"},
                    params=params or {}, json=json_body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Zoom unreachable during {what}: {exc}", retryable=True,
            ) from exc
        if response.status_code == 204:
            return {}
        _raise(response.status_code, response.text, what)
        try:
            return response.json()
        except Exception:
            return {}

    async def list_meetings(self, creds: dict, user_id: str = "me", timeout: float = 30.0) -> list:
        uid = str(user_id or "me").strip() or "me"
        data = await self._request("GET", f"/users/{uid}/meetings", creds, params={"type": "scheduled"}, what="list meetings", timeout=timeout)
        items = data.get("meetings", []) if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    async def get_meeting(self, creds: dict, meeting_id: str, timeout: float = 30.0) -> dict:
        if not str(meeting_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_meeting needs a meeting_id.", retryable=False)
        data = await self._request("GET", f"/meetings/{str(meeting_id).strip()}", creds, what="get meeting", timeout=timeout)
        return data if isinstance(data, dict) else {}

    async def create_meeting(
        self, creds: dict, user_id: str, topic: str, start_time: str = "", duration_min: int = 30, timeout: float = 30.0,
    ) -> dict:
        uid = str(user_id or "me").strip() or "me"
        if not str(topic or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_meeting needs a topic.", retryable=False)
        body: dict[str, Any] = {"topic": topic.strip(), "type": 2, "duration": max(1, min(duration_min, 1440))}
        if str(start_time or "").strip():
            body["start_time"] = start_time.strip()
        data = await self._request("POST", f"/users/{uid}/meetings", creds, json_body=body, what="create meeting", timeout=timeout)
        return data if isinstance(data, dict) else {}

    async def delete_meeting(self, creds: dict, meeting_id: str, timeout: float = 30.0) -> dict:
        if not str(meeting_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "delete_meeting needs a meeting_id.", retryable=False)
        await self._request("DELETE", f"/meetings/{str(meeting_id).strip()}", creds, what="delete meeting", timeout=timeout)
        return {"deleted": True, "meeting_id": str(meeting_id).strip()}
