"""GitLab connector implementing the ConnectorSDK interface."""

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
from app.providers.gitlab import GitLabProviderClient


class GitLabConnectorParams(BaseModel):
    operation: str = Field(default="list_issues")
    project_id: str = ""
    issue_iid: str = ""
    title: str = ""
    description: str = ""
    body: str = ""
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class GitLabConnector(ConnectorSDK):
    connector_id = "gitlab"
    display_name = "GitLab"
    description = "Work with GitLab projects, issues, notes, and merge requests."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GitLabProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["gitlab"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("access_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = GitLabConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid GitLab payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("gitlab") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        pid = str(raw.get("project_id") or params.project_id)
        try:
            if op == "list_issues":
                issues = await self._provider.list_issues(creds, pid, timeout=timeout)
                return {"issues": issues}
            if op == "get_issue":
                return await self._provider.get_issue(creds, pid, str(raw.get("issue_iid") or params.issue_iid), timeout=timeout)
            if op == "create_issue":
                return await self._provider.create_issue(
                    creds, pid, str(raw.get("title") or params.title),
                    str(raw.get("description") or params.description), timeout=timeout,
                )
            if op == "add_note":
                return await self._provider.add_note(
                    creds, pid, str(raw.get("issue_iid") or params.issue_iid),
                    str(raw.get("body") or params.body), timeout=timeout,
                )
            if op == "list_merge_requests":
                mrs = await self._provider.list_merge_requests(creds, pid, timeout=timeout)
                return {"merge_requests": mrs}
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported GitLab operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (/user); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_issues", "get_issue", "create_issue", "add_note", "list_merge_requests"]}}
