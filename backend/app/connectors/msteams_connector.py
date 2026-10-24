"""Microsoft Teams connector implementing the ConnectorSDK interface.

Thin mapper over MicrosoftGraphProviderClient; credentials arrive via
context["credentials"]["microsoft_graph"] (tenant/client id/secret) and
access tokens are minted + cached server-side.
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
from app.providers.microsoft_graph import MicrosoftGraphProviderClient


class MSTeamsConnectorParams(BaseModel):
    operation: str = Field(
        default="send_message",
        description=(
            "send_message | list_teams | list_channels | list_channel_messages | "
            "reply_to_message | list_members | create_channel."
        ),
    )
    team_id: str = ""
    channel_id: str = ""
    content: str = ""
    subject: str = ""
    message_id: str = ""
    top: int = Field(default=20, ge=1, le=50)
    display_name: str = ""
    description: str = ""
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class MSTeamsConnector(ConnectorSDK):
    connector_id = "msteams"
    display_name = "Microsoft Teams"
    description = "Send messages and browse teams/channels in Microsoft Teams."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = MicrosoftGraphProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["msteams"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(
            str(config.get("tenant_id") or "").strip()
            and str(config.get("client_id") or "").strip()
            and str(config.get("client_secret") or "").strip()
        )

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._provider.reset()
        self._metadata.clear()

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        return await self._provider.test_connection(creds)

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = MSTeamsConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Microsoft Teams payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("microsoft_graph") or {}

        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()

        try:
            if op == "send_message":
                raw = payload or {}
                team_id = str(raw.get("team_id") or params.team_id)
                channel_id = str(raw.get("channel_id") or params.channel_id)
                content = str(raw.get("content") or params.content)
                subject = str(raw.get("subject") or params.subject)
                if not team_id or not channel_id:
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST,
                        "send_message requires team_id and channel_id.",
                        retryable=False,
                    )
                return await self._provider.send_channel_message(
                    creds, team_id, channel_id, content, subject=subject,
                    timeout=params.timeout_seconds,
                )
            if op == "list_teams":
                return await self._provider.list_teams(creds, timeout=params.timeout_seconds)
            if op == "list_channels":
                team_id = str((payload or {}).get("team_id") or params.team_id)
                if not team_id:
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST, "list_channels requires team_id.", retryable=False,
                    )
                return await self._provider.list_channels(creds, team_id, timeout=params.timeout_seconds)
            if op == "list_channel_messages":
                team_id = str((payload or {}).get("team_id") or params.team_id)
                channel_id = str((payload or {}).get("channel_id") or params.channel_id)
                return await self._provider.list_channel_messages(
                    creds, team_id, channel_id, top=params.top,
                    timeout=params.timeout_seconds,
                )
            if op == "reply_to_message":
                team_id = str((payload or {}).get("team_id") or params.team_id)
                channel_id = str((payload or {}).get("channel_id") or params.channel_id)
                message_id = str((payload or {}).get("message_id") or params.message_id)
                content = str((payload or {}).get("content") or params.content)
                return await self._provider.reply_to_channel_message(
                    creds, team_id, channel_id, message_id, content,
                    timeout=params.timeout_seconds,
                )
            if op == "list_members":
                team_id = str((payload or {}).get("team_id") or params.team_id)
                return await self._provider.list_team_members(
                    creds, team_id, timeout=params.timeout_seconds,
                )
            if op == "create_channel":
                team_id = str((payload or {}).get("team_id") or params.team_id)
                display_name = str((payload or {}).get("display_name") or params.display_name)
                description = str((payload or {}).get("description") or params.description)
                return await self._provider.create_channel(
                    creds, team_id, display_name, description=description,
                    timeout=params.timeout_seconds,
                )
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported Microsoft Teams operation '{operation}'.", retryable=False,
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
