"""Trello connector implementing the ConnectorSDK interface.

Thin mapper over TrelloProviderClient with per-op contracts.
"""

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
from app.providers.trello import TrelloProviderClient


class TrelloConnectorParams(BaseModel):
    operation: str = Field(default="list_cards")
    board_id: str = ""
    card_id: str = ""
    list_id: str = ""
    name: str = ""
    desc: str = ""
    text: str = ""
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class TrelloConnector(ConnectorSDK):
    connector_id = "trello"
    display_name = "Trello"
    description = "Work with Trello boards, cards, and comments."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = TrelloProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["trello"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_key") or "").strip() and str(config.get("api_token") or "").strip())

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
            params = TrelloConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Trello payload: {exc}", retryable=False,
            ) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("trello") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_cards":
                cards = await self._provider.list_cards(creds, str(raw.get("board_id") or params.board_id), timeout=timeout)
                return {"cards": cards}
            if op == "get_card":
                return await self._provider.get_card(creds, str(raw.get("card_id") or params.card_id), timeout=timeout)
            if op == "create_card":
                return await self._provider.create_card(
                    creds, str(raw.get("list_id") or params.list_id),
                    str(raw.get("name") or params.name), str(raw.get("desc") or params.desc),
                    timeout=timeout,
                )
            if op == "add_comment":
                return await self._provider.add_comment(
                    creds, str(raw.get("card_id") or params.card_id),
                    str(raw.get("text") or params.text), timeout=timeout,
                )
        except Exception as exc:
            from app.connectors import ConnectorError

            if isinstance(exc, ConnectorError):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Trello {op} failed: {exc}", retryable=True) from exc
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Trello operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (members/me); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_cards", "get_card", "create_card", "add_comment"]}}
