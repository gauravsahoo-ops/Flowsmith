"""Google Drive connector implementing the ConnectorSDK interface.

Operation mapper over GoogleDriveProviderClient (Drive v3). Credentials
arrive via context["credentials"]["google_drive"]; OAuth refresh is
handled by BaseProviderClient with server-side app credentials.
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
from app.providers.google_drive import GoogleDriveProviderClient


class GoogleDriveConnectorParams(BaseModel):
    operation: str = Field(default="list_files", description="list_files | upload_file | get_file.")
    folder_id: str = ""
    file_id: str = ""
    name: str = ""
    content: str = ""
    mime_type: str = "text/plain"
    is_base64: bool = False
    page_size: int = Field(default=50, ge=1, le=100)
    max_pages: int = Field(default=3, ge=1, le=20)
    query_extra: str = ""
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class GoogleDriveConnector(ConnectorSDK):
    connector_id = "google_drive"
    display_name = "Google Drive"
    description = "List, inspect and create files in Google Drive."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GoogleDriveProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["google_drive"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("refresh_token") or "").strip()) or bool(config.get("oauth"))

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._provider.reset()
        self._metadata.clear()

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = GoogleDriveConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Google Drive payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("google_drive") or {}

        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()

        try:
            if op == "list_files":
                return await self._provider.list_files(
                    creds, folder_id=params.folder_id, page_size=params.page_size,
                    max_pages=params.max_pages, query_extra=params.query_extra,
                    timeout=params.timeout_seconds,
                )
            if op == "upload_file":
                content = str((payload or {}).get("content") if isinstance(payload, dict) else "") or params.content
                return await self._provider.upload_file(
                    creds, name=str(payload.get("name") if isinstance(payload, dict) else "") or params.name,
                    content=content, mime_type=params.mime_type, folder_id=params.folder_id,
                    is_base64=params.is_base64, timeout=max(params.timeout_seconds, 60.0),
                )
            if op == "get_file":
                fid = str((payload or {}).get("file_id") if isinstance(payload, dict) else "") or params.file_id
                if not fid:
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST, "operation=get_file requires file_id.", retryable=False,
                    )
                return await self._provider.get_file(creds, fid, timeout=params.timeout_seconds)
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported Google Drive operation '{operation}'.", retryable=False,
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
