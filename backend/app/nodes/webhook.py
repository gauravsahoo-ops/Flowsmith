"""Webhook trigger node (spec 7, node #3, section 32).

A public URL starts the workflow. The node receives the raw HTTP
payload as trigger items and normalizes it into standard items:

    {"body": <payload>, "headers": {...}, "query": {...}, "params": {...}}

A list body expands into one output item per element.

The webhook path registration in the database is the API layer's job
(M7); this node only declares and validates the path parameter.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

_PATH_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


class WebhookTriggerParams(BaseModel):
    path: str = Field(min_length=1, description="URL suffix, e.g. 'incoming-email' (letters, digits, - and _).")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"

    def model_post_init(self, __context: Any) -> None:
        if not _PATH_RE.match(self.path):
            raise ValueError(
                f"Invalid webhook path '{self.path}': use only letters, digits, '-' and '_'."
            )


@register
class WebhookTriggerNode(BaseNode[WebhookTriggerParams]):
    node_type = "webhook"
    display_name = "Webhook Trigger"
    version = 1
    description = "Starts the workflow when someone calls its public URL."
    category = "Triggers"
    icon = "webhook"
    parameters_schema = WebhookTriggerParams
    input_handles: list[str] = []

    async def run(
        self,
        ctx: NodeContext,
        params: WebhookTriggerParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        if not input_items:
            return NodeResult(output_items=[{"success": True, "body": {}, "headers": {}, "query": {}, "params": {}}])

        output_items: list[dict[str, Any]] = []
        for item in input_items:
            if isinstance(item, dict) and "body" in item:
                # Already shaped like {body, headers, query, params}.
                output_items.append({"success": True, **item})
                continue
            body = item
            if isinstance(body, list):
                for element in body:
                    output_items.append({"success": True, "body": element, "headers": {}, "query": {}, "params": {}})
            else:
                output_items.append({"success": True, "body": body, "headers": {}, "query": {}, "params": {}})
        return NodeResult(output_items=output_items)
