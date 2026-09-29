"""Box connector implementing the ConnectorSDK interface."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorCategory,
    ConnectorErrorCode,
    ConnectorSDK,
    ConnectorStatus,
    make_connector_error,
)
from app.providers.box import BoxProviderClient


class BoxConnectorParams(BaseModel):
    operation: str = Field(default="list_folder_items")
    folder_id: str = "0"
    file_id: str = ""
    name: str = ""
    parent_id: str = "0"
    query: str = ""
    content: str = ""
    type_filter: str = ""
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class BoxConnector(ConnectorSDK):
    connector_id = "box"
    display_name = "Box"
    description = "Manage cloud content, enterprise documents, folders, and full-text search via Box API v2."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = BoxProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["box"]

    async def connect(self, config: dict[str, Any]) -> bool:
        token = str(config.get("access_token") or config.get("token") or "").strip()
        return bool(token)

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = BoxConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Box payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("box") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        folder_id = str(raw.get("folder_id") or params.folder_id or "0").strip()
        file_id = str(raw.get("file_id") or params.file_id or "").strip()
        name = str(raw.get("name") or params.name or "").strip()
        parent_id = str(raw.get("parent_id") or params.parent_id or "0").strip()
        query = str(raw.get("query") or params.query or "").strip()
        content = raw.get("content", params.content)
        limit = int(raw.get("limit") or params.limit)
        offset = int(raw.get("offset") or params.offset)

        try:
            if op == "list_folder_items":
                return await self._provider.list_folder_items(creds, folder_id=folder_id, limit=limit, offset=offset, timeout=timeout)

            if op == "get_file":
                if not file_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "file_id is required for get_file.", retryable=False)
                return await self._provider.get_file(creds, file_id, timeout=timeout)

            if op == "create_folder":
                if not name:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Folder name is required for create_folder.", retryable=False)
                return await self._provider.create_folder(creds, name=name, parent_id=parent_id, timeout=timeout)

            if op == "delete_file":
                if not file_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "file_id is required for delete_file.", retryable=False)
                return await self._provider.delete_file(creds, file_id, timeout=timeout)

            if op == "search":
                if not query:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Search query is required.", retryable=False)
                type_filter = str(raw.get("type_filter") or params.type_filter or "").strip() or None
                return await self._provider.search(creds, query=query, limit=limit, offset=offset, type_filter=type_filter, timeout=timeout)

            if op == "upload_file":
                if not name:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "File name is required for upload_file.", retryable=False)
                if content is None:
                    content = ""
                return await self._provider.upload_file(creds, name=name, content=content, parent_id=parent_id, timeout=timeout)

        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Box {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Box operation '{operation}'.", retryable=False)
