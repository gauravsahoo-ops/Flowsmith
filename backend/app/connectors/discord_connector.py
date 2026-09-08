"""Discord connector implementing the ConnectorSDK interface.

Thin mapper over DiscordProviderClient. send_message uses the stored
bot token credential; send_webhook takes a webhook URL per call.
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
from app.providers.discord import DiscordProviderClient


class DiscordConnectorParams(BaseModel):
    operation: str = Field(default="send_message", description="send_message | send_webhook.")
    channel_id: str = ""
    content: str = ""
    webhook_url: str = ""
    username: str = ""
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class DiscordConnector(ConnectorSDK):
    connector_id = "discord"
    display_name = "Discord"
    description = "Send Discord messages via bot API or incoming webhooks."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = DiscordProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["discord"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("bot_token") or "").strip())

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
            params = DiscordConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Discord payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("discord") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()

        try:
            if op == "send_message":
                return await self._provider.send_message(
                    creds, str(raw.get("channel_id") or params.channel_id),
                    str(raw.get("content") or params.content),
                    timeout=params.timeout_seconds,
                )
            if op == "send_webhook":
                return await self._provider.send_webhook(
                    str(raw.get("webhook_url") or params.webhook_url),
                    str(raw.get("content") or params.content),
                    username=str(raw.get("username") or params.username),
                    timeout=params.timeout_seconds,
                )
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported Discord operation '{operation}'.", retryable=False,
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
