"""Jira connector implementing the ConnectorSDK interface.

Thin mapper over JiraProviderClient; credentials arrive via
context["credentials"]["jira"].
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
from app.providers.jira import JiraProviderClient


class JiraConnectorParams(BaseModel):
    operation: str = Field(default="search", description="search | create_issue | update_issue | add_comment.")
    jql: str = ""
    project_key: str = ""
    issue_type: str = "Task"
    summary: str = ""
    description: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)
    issue_key: str = ""
    body: str = ""
    max_results: int = Field(default=50, ge=1, le=100)
    max_pages: int = Field(default=3, ge=1, le=10)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class JiraConnector(ConnectorSDK):
    connector_id = "jira"
    display_name = "Jira"
    description = "Search, create and update issues in Jira Cloud."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = JiraProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["jira"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(
            str(config.get("site_url") or "").strip()
            and str(config.get("email") or "").strip()
            and str(config.get("api_token") or "").strip()
        )

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
            params = JiraConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Jira payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("jira") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        try:
            if op == "search":
                return await self._provider.search(
                    creds, str(raw.get("jql") or params.jql),
                    max_results=params.max_results, max_pages=params.max_pages,
                    timeout=timeout,
                )
            if op == "create_issue":
                fields_raw = raw.get("fields")
                extra = fields_raw if isinstance(fields_raw, dict) else None
                return await self._provider.create_issue(
                    creds,
                    str(raw.get("project_key") or params.project_key),
                    str(raw.get("issue_type") or params.issue_type),
                    str(raw.get("summary") or params.summary),
                    description=str(raw.get("description") or params.description),
                    extra_fields=extra, timeout=timeout,
                )
            if op == "update_issue":
                fields_raw = raw.get("fields")
                if not isinstance(fields_raw, dict) or not fields_raw:
                    if params.fields:
                        fields_raw = params.fields
                    else:
                        raise make_connector_error(
                            ConnectorErrorCode.BAD_REQUEST, "update_issue requires a fields map.", retryable=False,
                        )
                return await self._provider.update_issue(
                    creds, str(raw.get("issue_key") or params.issue_key),
                    fields_raw, timeout=timeout,
                )
            if op == "add_comment":
                return await self._provider.add_comment(
                    creds, str(raw.get("issue_key") or params.issue_key),
                    str(raw.get("body") or params.body), timeout=timeout,
                )
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported Jira operation '{operation}'.", retryable=False,
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
