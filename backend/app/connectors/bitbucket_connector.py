"""Bitbucket connector implementing the ConnectorSDK interface."""

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
from app.providers.bitbucket import BitbucketProviderClient


class BitbucketConnectorParams(BaseModel):
    operation: str = Field(default="list_repos")
    workspace: str = ""
    repo_slug: str = ""
    pr_id: str = ""
    text: str = ""
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class BitbucketConnector(ConnectorSDK):
    connector_id = "bitbucket"
    display_name = "Bitbucket"
    description = "Work with Bitbucket workspaces, repos, and pull requests."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = BitbucketProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["bitbucket"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("access_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = BitbucketConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Bitbucket payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("bitbucket") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        ws = str(raw.get("workspace") or params.workspace)
        repo = str(raw.get("repo_slug") or params.repo_slug)
        try:
            if op == "list_repos":
                repos = await self._provider.list_repos(creds, ws, timeout=timeout)
                return {"repos": repos}
            if op == "get_repo":
                return await self._provider.get_repo(creds, ws, repo, timeout=timeout)
            if op == "list_pull_requests":
                prs = await self._provider.list_pull_requests(creds, ws, repo, timeout=timeout)
                return {"pull_requests": prs}
            if op == "get_pull_request":
                return await self._provider.get_pull_request(
                    creds, ws, repo, str(raw.get("pr_id") or params.pr_id), timeout=timeout,
                )
            if op == "add_comment":
                return await self._provider.add_comment(
                    creds, ws, repo, str(raw.get("pr_id") or params.pr_id),
                    str(raw.get("text") or params.text), timeout=timeout,
                )
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Bitbucket operation '{operation}'.", retryable=False)

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_repos", "get_repo", "list_pull_requests", "get_pull_request", "add_comment"]}}
