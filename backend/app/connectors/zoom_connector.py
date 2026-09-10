"""Zoom connector implementing the ConnectorSDK interface."""

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
from app.providers.zoom import ZoomProviderClient


class ZoomConnectorParams(BaseModel):
    operation: str = Field(default="list_meetings")
    user_id: str = "me"
    meeting_id: str = ""
    topic: str = ""
    start_time: str = ""
    duration_min: int = Field(default=30, ge=1, le=1440)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class ZoomConnector(ConnectorSDK):
    connector_id = "zoom"
    display_name = "Zoom"
    description = "Work with Zoom users and meetings."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = ZoomProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["zoom"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("access_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = ZoomConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Zoom payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("zoom") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_meetings":
                meetings = await self._provider.list_meetings(creds, str(raw.get("user_id") or params.user_id), timeout=timeout)
                return {"meetings": meetings}
            if op == "get_meeting":
                return await self._provider.get_meeting(creds, str(raw.get("meeting_id") or params.meeting_id), timeout=timeout)
            if op == "create_meeting":
                return await self._provider.create_meeting(
                    creds, str(raw.get("user_id") or params.user_id),
                    str(raw.get("topic") or params.topic), str(raw.get("start_time") or params.start_time),
                    int(raw.get("duration_min") or params.duration_min), timeout=timeout,
                )
            if op == "delete_meeting":
                return await self._provider.delete_meeting(creds, str(raw.get("meeting_id") or params.meeting_id), timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Zoom operation '{operation}'.", retryable=False)

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
        return {"output": {"connector_id": self.connector_id, "operations": ["list_meetings", "get_meeting", "create_meeting", "delete_meeting"]}}
