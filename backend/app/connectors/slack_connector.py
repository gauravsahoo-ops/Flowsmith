"""Slack connector implementing the ConnectorSDK interface.

Bot-token Slack Web API operations. The legacy webhook-only 'slack'
*node* keeps its node type; this connector registers as 'slack_api'.
Credentials arrive via context["credentials"]["slack"]; Slack's 429
Retry-After is surfaced so the engine honors it.
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
from app.providers.slack import SlackProviderClient


class SlackConnectorParams(BaseModel):
    operation: str = Field(default="send_message", description="send_message | list_channels.")
    channel: str = ""
    text: str = ""
    thread_ts: str = ""
    limit: int = Field(default=100, ge=1, le=200)
    max_pages: int = Field(default=3, ge=1, le=10)
    exclude_archived: bool = True


class SlackConnector(ConnectorSDK):
    connector_id = "slack"
    display_name = "Slack"
    description = "Send messages to Slack channels and list workspace channels."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = SlackProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["slack_api"]

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
            params = SlackConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Slack payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("slack") or {}

        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()

        try:
            if op == "send_message":
                channel = str((payload or {}).get("channel") or params.channel)
                text = str((payload or {}).get("text") or params.text)
                thread_ts = str((payload or {}).get("thread_ts") or params.thread_ts)
                return await self._provider.send_message(
                    creds, channel, text, thread_ts=thread_ts,
                )
            if op == "list_channels":
                return await self._provider.list_channels(
                    creds, limit=params.limit, max_pages=params.max_pages,
                    exclude_archived=params.exclude_archived,
                )
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported Slack operation '{operation}'.", retryable=False,
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

