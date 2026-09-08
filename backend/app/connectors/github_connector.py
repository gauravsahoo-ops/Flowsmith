"""GitHub connector implementing the ConnectorSDK interface.

Thin mapper over GitHubProviderClient (REST v3, PAT auth); credentials
arrive via context["credentials"]["github"].
"""

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
from app.providers.github import GitHubProviderClient


class GitHubConnectorParams(BaseModel):
    operation: str = Field(default="get_repo", description="get_repo | create_issue | add_comment | list_issues.")
    owner: str = ""
    repo: str = ""
    title: str = ""
    body: str = ""
    labels: list[str] = Field(default_factory=list)
    issue_number: int = 0
    state: str = "open"
    per_page: int = Field(default=50, ge=1, le=100)
    max_pages: int = Field(default=3, ge=1, le=10)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class GitHubConnector(ConnectorSDK):
    connector_id = "github"
    display_name = "GitHub"
    description = "Inspect repositories and manage issues on GitHub."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GitHubProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["github"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("access_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = GitHubConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid GitHub payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("github") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        owner = str(raw.get("owner") or params.owner)
        repo = str(raw.get("repo") or params.repo)
        timeout = float(raw.get("timeout_seconds") or params.timeout_seconds)

        try:
            if op == "get_repo":
                return await self._provider.get_repo(creds, owner, repo, timeout=timeout)
            if op == "create_issue":
                labels_raw = raw.get("labels")
                labels = [str(lb) for lb in labels_raw] if isinstance(labels_raw, list) else params.labels
                return await self._provider.create_issue(
                    creds, owner, repo, str(raw.get("title") or params.title),
                    body=str(raw.get("body") or params.body),
                    labels=labels or None, timeout=timeout,
                )
            if op == "add_comment":
                number_raw = raw.get("issue_number", params.issue_number)
                try:
                    number = int(number_raw)
                except (TypeError, ValueError) as exc:
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST, "issue_number must be an integer.", retryable=False,
                    ) from exc
                return await self._provider.add_comment(
                    creds, owner, repo, number,
                    str(raw.get("body") or params.body), timeout=timeout,
                )
            if op == "list_issues":
                state = str(raw.get("state") or params.state)
                per_page_raw = raw.get("per_page")
                max_pages_raw = raw.get("max_pages")
                return await self._provider.list_issues(
                    creds, owner, repo, state=state,
                    per_page=int(per_page_raw) if per_page_raw is not None else params.per_page,
                    max_pages=int(max_pages_raw) if max_pages_raw is not None else params.max_pages,
                    timeout=timeout,
                )
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported GitHub operation '{operation}'.", retryable=False,
        )

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "output": {
                "connector_id": self.connector_id,
                "name": self.name,
                "status": self.status,
                "metadata": self._metadata,
            },
            "success": True,
        }

    async def op_describe(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": self.to_dict(), "success": True}
