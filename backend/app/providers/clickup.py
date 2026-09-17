"""ClickUp provider client.

ClickUp REST API v2 with personal API token auth (Authorization header).
Ops: list/get/create/update tasks, add comment. 429/5xx retryable.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

CLICKUP_API_BASE = "https://api.clickup.com/api/v2"


def _key(creds: dict) -> str:
    token = str((creds or {}).get("api_key") or "").strip()
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "ClickUp connector needs a 'clickup' credential with api_key.",
            retryable=False,
        )
    return token


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    detail = ""
    if isinstance(payload, dict):
        err = payload.get("err") or payload.get("error") or payload.get("message")
        if err:
            detail = f": {str(err)[:200]}"
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"ClickUp auth failed during {what}{detail}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"ClickUp forbade {what}{detail}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"ClickUp resource missing during {what}{detail}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"ClickUp rate limited during {what}{detail}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"ClickUp unavailable during {what}{detail}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"ClickUp rejected {what}{detail or ': ' + body[:200]}.", retryable=False)


class ClickUpProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (authorized user)."""
        data = await self._get(creds, "/user", "test connection")
        username = ((data.get("user") or {}) if isinstance(data, dict) else {}).get("username", "")
        return {"ok": True, "message": f"Connected as {username}." if username else "Connected."}

    async def _request(
        self, creds: dict, method: str, path: str, what: str,
        params: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{CLICKUP_API_BASE}{path}",
                    headers={"Authorization": _key(creds), "Content-Type": "application/json"},
                    params=params or {}, json=body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"ClickUp unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload

    async def _get(self, creds: dict, path: str, what: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        out = await self._request(creds, "GET", path, what, params=params, timeout=timeout)
        return out if isinstance(out, dict) else {}

    async def list_tasks(self, creds: dict, list_id: str, limit: int = 25, timeout: float = 30.0) -> dict:
        if not str(list_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "list_tasks needs a list_id.", retryable=False)
        return await self._get(creds, f"/list/{list_id}/task", "list_tasks",
                               params={"archived": "false", "limit": max(1, min(int(limit or 25), 100))}, timeout=timeout)

    async def get_task(self, creds: dict, task_id: str, timeout: float = 30.0) -> dict:
        if not str(task_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_task needs a task_id.", retryable=False)
        return await self._get(creds, f"/task/{task_id}", "get_task", timeout=timeout)

    async def create_task(
        self, creds: dict, list_id: str, name: str, description: str = "",
        status: str = "", timeout: float = 30.0,
    ) -> dict:
        if not str(list_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_task needs a list_id.", retryable=False)
        if not str(name or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_task needs a name.", retryable=False)
        body: dict[str, Any] = {"name": name}
        if description:
            body["description"] = description
        if status:
            body["status"] = status
        out = await self._request(creds, "POST", f"/list/{list_id}/task", "create_task", body=body, timeout=timeout)
        return out if isinstance(out, dict) else {}

    async def update_task(self, creds: dict, task_id: str, fields: dict[str, Any], timeout: float = 30.0) -> dict:
        if not str(task_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_task needs a task_id.", retryable=False)
        if not fields:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_task needs fields to update.", retryable=False)
        out = await self._request(creds, "PUT", f"/task/{task_id}", "update_task", body=fields, timeout=timeout)
        return out if isinstance(out, dict) else {}

    async def add_comment(self, creds: dict, task_id: str, comment_text: str, timeout: float = 30.0) -> dict:
        if not str(task_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs a task_id.", retryable=False)
        if not str(comment_text or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs comment_text.", retryable=False)
        out = await self._request(creds, "POST", f"/task/{task_id}/comment", "add_comment",
                                  body={"comment_text": comment_text}, timeout=timeout)
        return out if isinstance(out, dict) else {}
