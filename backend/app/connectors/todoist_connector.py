"""Todoist connector implementing the ConnectorSDK interface."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorCategory,
    ConnectorError,
    ConnectorErrorCode,
    ConnectorSDK,
    ConnectorStatus,
    make_connector_error,
)
from app.providers.todoist import TodoistProviderClient


class TodoistConnectorParams(BaseModel):
    operation: str = Field(default="list_tasks")
    task_id: str = ""
    content: str = ""
    description: str = ""
    limit: int = Field(default=25, ge=1, le=200)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class TodoistConnector(ConnectorSDK):
    connector_id = "todoist"
    display_name = "Todoist"
    description = "Manage Todoist tasks and comments."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = TodoistProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["todoist"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = TodoistConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Todoist payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("todoist") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_tasks":
                return await self._provider.list_tasks(
                    creds, int(raw.get("limit") or params.limit), timeout=timeout)
            if op == "get_task":
                return await self._provider.get_task(
                    creds, str(raw.get("task_id") or params.task_id), timeout=timeout)
            if op == "create_task":
                return await self._provider.create_task(
                    creds, str(raw.get("content") or params.content),
                    str(raw.get("description") or params.description), timeout=timeout)
            if op == "update_task":
                fields = {k: str(raw.get(k) if raw.get(k) is not None else getattr(params, k))
                          for k in ("content", "description")}
                fields = {k: v for k, v in fields.items() if v}
                return await self._provider.update_task(
                    creds, str(raw.get("task_id") or params.task_id), fields, timeout=timeout)
            if op == "close_task":
                return await self._provider.close_task(
                    creds, str(raw.get("task_id") or params.task_id), timeout=timeout)
            if op == "add_comment":
                return await self._provider.add_comment(
                    creds, str(raw.get("task_id") or params.task_id),
                    str(raw.get("content") or params.content), timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Todoist operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (projects list); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_tasks", "get_task", "create_task", "update_task", "close_task", "add_comment"]}}
