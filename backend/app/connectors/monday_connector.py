"""Monday.com connector implementing the ConnectorSDK interface."""

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
from app.providers.monday import MondayProviderClient


class MondayConnectorParams(BaseModel):
    operation: str = Field(default="list_boards")
    board_id: str = ""
    item_id: str = ""
    group_id: str = ""
    item_name: str = ""
    body: str = ""
    limit: int = Field(default=25, ge=1, le=100)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class MondayConnector(ConnectorSDK):
    connector_id = "monday"
    display_name = "Monday.com"
    description = "Work with Monday.com boards, items, and updates."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = MondayProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["monday"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = MondayConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Monday payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("monday") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_boards":
                return await self._provider.list_boards(
                    creds, int(raw.get("limit") or params.limit), timeout=timeout)
            if op == "get_board":
                return await self._provider.get_board(
                    creds, str(raw.get("board_id") or params.board_id), timeout=timeout)
            if op == "list_items":
                return await self._provider.list_items(
                    creds, str(raw.get("board_id") or params.board_id),
                    int(raw.get("limit") or params.limit), timeout=timeout)
            if op == "create_item":
                return await self._provider.create_item(
                    creds, str(raw.get("board_id") or params.board_id),
                    str(raw.get("item_name") or params.item_name),
                    str(raw.get("group_id") or params.group_id), timeout=timeout)
            if op == "add_update":
                return await self._provider.add_update(
                    creds, str(raw.get("item_id") or params.item_id),
                    str(raw.get("body") or params.body), timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Monday operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (viewer query); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_boards", "get_board", "list_items", "create_item", "add_update"]}}
