"""Todoist provider client.

Todoist REST API v2 with Bearer personal API token.
Ops: list/get/create/update/close tasks, add comment. 429/5xx retryable.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

TODOIST_API_BASE = "https://api.todoist.com/api/v2"


def _key(creds: dict) -> str:
    token = str((creds or {}).get("api_token") or "").strip()
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Todoist connector needs a 'todoist' credential with api_token.",
            retryable=False,
        )
    return token


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Todoist auth failed during {what}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Todoist forbade {what}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Todoist resource missing during {what}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Todoist rate limited during {what}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Todoist unavailable during {what}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Todoist rejected {what}: {body[:200]}.", retryable=False)


class TodoistProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (projects list)."""
        data = await self._get(creds, "/projects", "test connection", params={"limit": 1})
        projects = data.get("results", []) if isinstance(data, dict) else []
        return {"ok": True, "message": f"Connected ({len(projects)} project(s) visible)."} if projects else {"ok": True, "message": "Connected."}

    async def _request(
        self, creds: dict, method: str, path: str, what: str,
        params: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{TODOIST_API_BASE}{path}",
                    headers={"Authorization": f"Bearer {_key(creds)}", "Content-Type": "application/json"},
                    params=params or {}, json=body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Todoist unreachable during {what}: {exc}", retryable=True,
            ) from exc
        if response.status_code == 204:
            return {}
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload

    async def _get(self, creds: dict, path: str, what: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        out = await self._request(creds, "GET", path, what, params=params, timeout=timeout)
        return out if isinstance(out, dict) else {}

    async def list_tasks(self, creds: dict, limit: int = 25, timeout: float = 30.0) -> dict:
        return await self._get(creds, "/tasks", "list_tasks",
                               params={"limit": max(1, min(int(limit or 25), 200))}, timeout=timeout)

    async def get_task(self, creds: dict, task_id: str, timeout: float = 30.0) -> dict:
        if not str(task_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_task needs a task_id.", retryable=False)
        return await self._get(creds, f"/tasks/{task_id}", "get_task", timeout=timeout)

    async def create_task(self, creds: dict, content: str, description: str = "", timeout: float = 30.0) -> dict:
        if not str(content or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_task needs content.", retryable=False)
        body: dict[str, Any] = {"content": content}
        if description:
            body["description"] = description
        out = await self._request(creds, "POST", "/tasks", "create_task", body=body, timeout=timeout)
        return out if isinstance(out, dict) else {}

    async def update_task(self, creds: dict, task_id: str, fields: dict[str, Any], timeout: float = 30.0) -> dict:
        if not str(task_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_task needs a task_id.", retryable=False)
        if not fields:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_task needs fields to update.", retryable=False)
        out = await self._request(creds, "POST", f"/tasks/{task_id}", "update_task", body=fields, timeout=timeout)
        return out if isinstance(out, dict) else {}

    async def close_task(self, creds: dict, task_id: str, timeout: float = 30.0) -> dict:
        if not str(task_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "close_task needs a task_id.", retryable=False)
        await self._request(creds, "POST", f"/tasks/{task_id}/close", "close_task", timeout=timeout)
        return {"ok": True, "id": task_id}

    async def add_comment(self, creds: dict, task_id: str, content: str, timeout: float = 30.0) -> dict:
        if not str(task_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs a task_id.", retryable=False)
        if not str(content or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs content.", retryable=False)
        out = await self._request(creds, "POST", "/comments", "add_comment",
                                  body={"task_id": task_id, "content": content}, timeout=timeout)
        return out if isinstance(out, dict) else {}
