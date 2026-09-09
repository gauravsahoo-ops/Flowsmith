"""Linear connector implementing the ConnectorSDK interface."""

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
from app.providers.linear import LinearProviderClient


class LinearConnectorParams(BaseModel):
    operation: str = Field(default="list_issues")
    team_id: str = ""
    issue_id: str = ""
    title: str = ""
    description: str = ""
    body: str = ""
    limit: int = Field(default=25, ge=1, le=100)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class LinearConnector(ConnectorSDK):
    connector_id = "linear"
    display_name = "Linear"
    description = "Work with Linear teams, issues, and comments."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = LinearProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["linear"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_key") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = LinearConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Linear payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("linear") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_issues":
                issues = await self._provider.list_issues(
                    creds, str(raw.get("team_id") or params.team_id),
                    int(raw.get("limit") or params.limit), timeout=timeout,
                )
                return {"issues": issues}
            if op == "get_issue":
                return await self._provider.get_issue(creds, str(raw.get("issue_id") or params.issue_id), timeout=timeout)
            if op == "create_issue":
                return await self._provider.create_issue(
                    creds, str(raw.get("team_id") or params.team_id),
                    str(raw.get("title") or params.title), str(raw.get("description") or params.description),
                    timeout=timeout,
                )
            if op == "update_issue":
                fields = {k: str(raw.get(k) or getattr(params, k)) for k in ("title", "description")}
                fields = {k: v for k, v in fields.items() if v}
                return await self._provider.update_issue(creds, str(raw.get("issue_id") or params.issue_id), fields, timeout=timeout)
            if op == "add_comment":
                return await self._provider.add_comment(
                    creds, str(raw.get("issue_id") or params.issue_id),
                    str(raw.get("body") or params.body), timeout=timeout,
                )
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Linear operation '{operation}'.", retryable=False)

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_issues", "get_issue", "create_issue", "update_issue", "add_comment"]}}
