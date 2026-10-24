"""Generic HTTP polling trigger node.

The polling daemon calls the configured URL, extracts a JSON array, deduplicates
items, and starts the workflow with the new items. The node itself is a passive
trigger shape and does not perform HTTP during normal execution.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class HttpPollTriggerParams(BaseModel):
    url: str = Field(min_length=8, max_length=2048, description="HTTP(S) endpoint to poll.")
    method: Literal["GET", "POST"] = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    items_path: str = Field(default="", max_length=255)
    dedupe_field: str = Field(default="", max_length=255)
    interval_seconds: int = Field(default=60, ge=30, le=86400)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError("Polling URL must use http:// or https://.")
        return value

    @field_validator("items_path", "dedupe_field")
    @classmethod
    def validate_path(cls, value: str) -> str:
        value = value.strip()
        if value and not all(part.isidentifier() for part in value.split(".")):
            raise ValueError("Use a dot path such as 'data.items'.")
        return value


@register
class HttpPollTriggerNode(BaseNode[HttpPollTriggerParams]):
    node_type = "http_poll_trigger"
    display_name = "HTTP Polling Trigger"
    version = 1
    description = "Poll an HTTP endpoint on an interval and start when new JSON items appear."
    category = "Triggers"
    icon = "webhook"
    parameters_schema = HttpPollTriggerParams
    input_handles: list[str] = []

    async def run(
        self,
        ctx: NodeContext,
        params: HttpPollTriggerParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        output = []
        for item in input_items or [{}]:
            body = item.get("body", item) if isinstance(item, dict) else item
            output.append({"success": True, "body": body, "headers": {}, "query": {}, "params": {}})
        return NodeResult(output_items=output)
