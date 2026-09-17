"""Respond to Webhook node (Flow).

Sets the synchronous HTTP response for the webhook delivery that
triggered this execution. Only takes effect when the caller requests it
(``POST /webhooks/{path}?respond=true``); otherwise the delivery keeps
the default asynchronous 202 envelope and this node is a pass-through.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class RespondToWebhookParams(BaseModel):
    status_code: int = Field(default=200, ge=100, le=599, description="HTTP status for the webhook response.")
    respond_with: Literal["input", "first", "json"] = Field(
        default="input", description="'input': all input items; 'first': first item; 'json': static JSON body.",
    )
    response_body: str = Field(default="", description="Static JSON body when respond_with is 'json'.")


@register
class RespondToWebhookNode(BaseNode[RespondToWebhookParams]):
    node_type = "respond_to_webhook"
    display_name = "Respond to Webhook"
    version = 1
    description = "Return a synchronous HTTP response to the triggering webhook delivery"
    category = "Flow"
    icon = "↩️"
    parameters_schema = RespondToWebhookParams
    input_handles = ["main"]
    output_handles = ["main"]

    async def run(
        self,
        ctx: NodeContext,
        params: RespondToWebhookParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        if params.respond_with == "json":
            raw = (params.response_body or "").strip()
            if not raw:
                body: Any = {}
            else:
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = {"data": raw}
        elif params.respond_with == "first":
            body = input_items[0] if input_items else {}
        else:
            body = list(input_items)
        return NodeResult(output_items=[{"status_code": params.status_code, "body": body}])
