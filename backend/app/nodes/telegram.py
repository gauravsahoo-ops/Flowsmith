"""Telegram node (spec 7).

Sends a message to a Telegram chat via the Bot API.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class TelegramParams(BaseModel):
    bot_token: str = Field(min_length=1, description="Telegram bot token.")
    chat_id: str = Field(min_length=1, description="Target chat ID or username.")
    text: str = Field(default="", description="Message text.")
    parse_mode: Literal["Markdown", "HTML"] = Field(
        default="Markdown", description="Message parse mode."
    )
    timeout_seconds: float = Field(default=30.0, description="Request timeout.")


@register
class TelegramNode(BaseNode[TelegramParams]):
    node_type = "telegram"
    display_name = "Telegram"
    version = 1
    description = "Send a message to a Telegram chat."
    category = "Communication"
    icon = "📲"
    parameters_schema = TelegramParams
    credential_types = ["telegram"]

    async def run(
        self,
        ctx: NodeContext,
        params: TelegramParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        import httpx

        url = f"https://api.telegram.org/bot{params.bot_token}/sendMessage"

        payload: dict[str, Any] = {
            "chat_id": params.chat_id,
            "text": params.text,
            "parse_mode": params.parse_mode,
        }

        try:
            response = await ctx.http_client.post(
                url,
                json=payload,
                timeout=params.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NodeExecutionError(
                f"Telegram API failed: {exc}",
                code="TELEGRAM_API_ERROR",
                node_id=self.node_type,
                retryable=True,
            ) from exc

        return NodeResult(output_items=[{"success": True, "sent": True, "chat_id": params.chat_id}])
