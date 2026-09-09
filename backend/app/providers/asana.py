"""Asana provider client (Batch B, original implementation).

Personal-access-token Bearer auth. Ops: list project tasks, get task,
create task, update task, add story comment. 429/5xx are retryable.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

ASANA_API_BASE = "https://app.asana.com/api/1.0"


def _token(creds: dict) -> str:
    token = str((creds or {}).get("access_token") or "").strip()
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Asana connector needs an 'asana' credential with access_token.",
            retryable=False,
        )
    return token


def _raise(status: int, body: str, what: str) -> None:
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"Asana auth failed during {what}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Asana forbade {what}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"Asana resource missing during {what}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"Asana rate limited during {what}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Asana unavailable during {what}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Asana rejected {what}: {body[:200]}", retryable=False)


class AsanaProviderClient:
    async def _request(
        self, method: str, path: str, creds: dict, *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 30.0, what: str,
    ) -> Any:
        headers = {"Authorization": f"Bearer {_token(creds)}", "Accept": "application/json"}
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, f"{ASANA_API_BASE}{path}", headers=headers,
                    params=params, json=json_body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Asana unreachable during {what}: {exc}", retryable=True,
            ) from exc
        _raise(response.status_code, response.text, what)
        try:
            payload = response.json()
        except Exception:
            return {}
        return payload.get("data", payload)

    async def list_tasks(self, creds: dict, project_id: str, timeout: float = 30.0) -> list:
        if not str(project_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "list_tasks needs a project_id.", retryable=False)
        data = await self._request("GET", "/tasks", creds, params={"project": project_id.strip()}, timeout=timeout, what="list tasks")
        return data if isinstance(data, list) else []

    async def get_task(self, creds: dict, task_id: str, timeout: float = 30.0) -> dict:
        if not str(task_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "get_task needs a task_id.", retryable=False)
        data = await self._request("GET", f"/tasks/{task_id.strip()}", creds, timeout=timeout, what="get task")
        return data if isinstance(data, dict) else {}

    async def create_task(self, creds: dict, project_id: str, name: str, notes: str = "", timeout: float = 30.0) -> dict:
        if not str(project_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_task needs a project_id.", retryable=False)
        if not str(name or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_task needs a name.", retryable=False)
        data = await self._request(
            "POST", "/tasks", creds,
            json_body={"data": {"name": name.strip(), "notes": notes or "", "projects": [project_id.strip()]}},
            timeout=timeout, what="create task",
        )
        return data if isinstance(data, dict) else {}

    async def update_task(self, creds: dict, task_id: str, fields: dict[str, Any], timeout: float = 30.0) -> dict:
        if not str(task_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update_task needs a task_id.", retryable=False)
        allowed = {k: v for k, v in (fields or {}).items() if k in ("name", "notes", "due_on", "assignee")}
        data = await self._request(
            "PUT", f"/tasks/{task_id.strip()}", creds,
            json_body={"data": allowed}, timeout=timeout, what="update task",
        )
        return data if isinstance(data, dict) else {}

    async def add_comment(self, creds: dict, task_id: str, text: str, timeout: float = 30.0) -> dict:
        if not str(task_id or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs a task_id.", retryable=False)
        if not str(text or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "add_comment needs text.", retryable=False)
        data = await self._request(
            "POST", f"/tasks/{task_id.strip()}/stories", creds,
            json_body={"data": {"text": text.strip()}}, timeout=timeout, what="add comment",
        )
        return data if isinstance(data, dict) else {}
