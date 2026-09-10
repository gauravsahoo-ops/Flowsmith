"""Asana connector implementing the ConnectorSDK interface."""

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
from app.providers.asana import AsanaProviderClient


class AsanaConnectorParams(BaseModel):
    operation: str = Field(default="list_tasks")
    project_id: str = ""
    task_id: str = ""
    name: str = ""
    notes: str = ""
    due_on: str = ""
    assignee: str = ""
    text: str = ""
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class AsanaConnector(ConnectorSDK):
    connector_id = "asana"
    display_name = "Asana"
    description = "Work with Asana projects, tasks, and comments."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = AsanaProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["asana"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("access_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = AsanaConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Asana payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("asana") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_tasks":
                tasks = await self._provider.list_tasks(creds, str(raw.get("project_id") or params.project_id), timeout=timeout)
                return {"tasks": tasks}
            if op == "get_task":
                return await self._provider.get_task(creds, str(raw.get("task_id") or params.task_id), timeout=timeout)
            if op == "create_task":
                return await self._provider.create_task(
                    creds, str(raw.get("project_id") or params.project_id),
                    str(raw.get("name") or params.name), str(raw.get("notes") or params.notes), timeout=timeout,
                )
            if op == "update_task":
                fields = {k: str(raw.get(k) or getattr(params, k)) for k in ("name", "notes", "due_on", "assignee")}
                fields = {k: v for k, v in fields.items() if v}
                return await self._provider.update_task(creds, str(raw.get("task_id") or params.task_id), fields, timeout=timeout)
            if op == "add_comment":
                return await self._provider.add_comment(
                    creds, str(raw.get("task_id") or params.task_id),
                    str(raw.get("text") or params.text), timeout=timeout,
                )
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Asana operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (users/me); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_tasks", "get_task", "create_task", "update_task", "add_comment"]}}
