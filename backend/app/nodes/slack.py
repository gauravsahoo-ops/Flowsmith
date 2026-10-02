"""Slack node (spec 7).

Sends a message to a Slack channel via incoming webhook.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class SlackParams(BaseModel):
    webhook_url: str = Field(min_length=1, description="Slack incoming webhook URL.")
    channel: str = Field(default="#general", description="Target channel name or ID.")
    text: str = Field(default="", description="Message text.")
    username: str | None = Field(
        default=None, description="Override the bot username."
    )
    icon_emoji: str | None = Field(
        default=None, description="Override the bot icon emoji."
    )
    blocks: Any = Field(
        default=None,
        description="Block kit blocks (JSON string or dict).",
    )
    timeout_seconds: float = Field(default=30.0, description="Request timeout.")


@register
class SlackNode(BaseNode[SlackParams]):
    node_type = "slack"
    display_name = "Slack"
    version = 1
    description = "Send a message to a Slack channel."
    category = "Communication"
    icon = "slack"
    parameters_schema = SlackParams
    credential_types = ["slack"]

    async def run(
        self,
        ctx: NodeContext,
        params: SlackParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        import httpx

        payload: dict[str, Any] = {
            "channel": params.channel,
            "text": params.text,
        }
        if params.username:
            payload["username"] = params.username
        if params.icon_emoji:
            payload["icon_emoji"] = params.icon_emoji
        if params.blocks is not None:
            payload["blocks"] = params.blocks

        try:
            response = await ctx.http_client.post(
                params.webhook_url,
                json=payload,
                timeout=params.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NodeExecutionError(
                f"Slack webhook failed: {exc}",
                code="SLACK_WEBHOOK_ERROR",
                node_id=self.node_type,
                retryable=True,
            ) from exc

        return NodeResult(output_items=[{"success": True, "sent": True, "channel": params.channel}])
