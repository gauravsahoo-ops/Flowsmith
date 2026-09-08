"""Notion connector implementing the ConnectorSDK interface.

Thin mapper over NotionProviderClient; credentials arrive via
context["credentials"]["notion"].
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
from app.providers.notion import NotionProviderClient


class NotionConnectorParams(BaseModel):
    operation: str = Field(default="query_database", description="query_database | create_page | update_page.")
    database_id: str = ""
    page_id: str = ""
    filter: dict[str, Any] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    archived: bool = False
    page_size: int = Field(default=50, ge=1, le=100)
    max_pages: int = Field(default=3, ge=1, le=10)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class NotionConnector(ConnectorSDK):
    connector_id = "notion"
    display_name = "Notion"
    description = "Query databases and create/update pages in Notion."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = NotionProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["notion"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("integration_token") or "").strip())

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
            params = NotionConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Notion payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("notion") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()

        try:
            if op == "query_database":
                filter_raw = raw.get("filter")
                return await self._provider.query_database(
                    creds, str(raw.get("database_id") or params.database_id),
                    filter_obj=filter_raw if isinstance(filter_raw, dict) else None,
                    page_size=params.page_size, max_pages=params.max_pages,
                    timeout=params.timeout_seconds,
                )
            if op == "create_page":
                props = raw.get("properties")
                if not isinstance(props, dict) or not props:
                    props = params.properties
                return await self._provider.create_page(
                    creds, str(raw.get("database_id") or params.database_id),
                    props, timeout=params.timeout_seconds,
                )
            if op == "update_page":
                props_raw = raw.get("properties")
                props = props_raw if isinstance(props_raw, dict) and props_raw else (
                    params.properties or None
                )
                archived_raw = raw.get("archived", params.archived)
                return await self._provider.update_page(
                    creds, str(raw.get("page_id") or params.page_id),
                    properties=props, archived=bool(archived_raw),
                    timeout=params.timeout_seconds,
                )
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported Notion operation '{operation}'.", retryable=False,
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
