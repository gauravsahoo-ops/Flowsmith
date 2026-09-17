"""Dropbox connector implementing the ConnectorSDK interface."""

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
from app.providers.dropbox import DropboxProviderClient


class DropboxConnectorParams(BaseModel):
    operation: str = Field(default="list_folder")
    path: str = ""
    content: str = ""
    limit: int = Field(default=25, ge=1, le=2000)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class DropboxConnector(ConnectorSDK):
    connector_id = "dropbox"
    display_name = "Dropbox"
    description = "Browse, manage, and upload Dropbox files."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = DropboxProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["dropbox"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("access_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = DropboxConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Dropbox payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("dropbox") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_folder":
                return await self._provider.list_folder(
                    creds, str(raw.get("path") or params.path),
                    int(raw.get("limit") or params.limit), timeout=timeout)
            if op == "get_metadata":
                return await self._provider.get_metadata(creds, str(raw.get("path") or params.path), timeout=timeout)
            if op == "create_folder":
                return await self._provider.create_folder(creds, str(raw.get("path") or params.path), timeout=timeout)
            if op == "delete":
                return await self._provider.delete(creds, str(raw.get("path") or params.path), timeout=timeout)
            if op == "upload_text":
                return await self._provider.upload_text(
                    creds, str(raw.get("path") or params.path),
                    str(raw.get("content") or params.content), timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Dropbox operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (current account); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_folder", "get_metadata", "create_folder", "delete", "upload_text"]}}
