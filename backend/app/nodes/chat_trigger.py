"""Chat trigger node (original implementation).

A public chat URL starts the workflow per message. The API layer owns
registration (same `webhooks` table, reserved `chat/` namespace) and
delivery: each POST carries `{message, session_id, history}` and the
run waits for completion so the HTTP response carries the reply.

Downstream items look like:

    {"success": True, "message": "...", "session_id": "...", "history": [...]}

Reply convention: the response scans terminal outputs for the first
`reply` / `response` / `text` / `output` string field.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from app.triggers.registry import CHAT_TRIGGER_PREFIX

_PATH_RE = re.compile(r"^[A-Za-z0-9/_.\-]+$")


class ChatTriggerParams(BaseModel):
    path: str = Field(min_length=1, description="Public path, e.g. 'chat/support-abcdefgh12345678'.")
    title: str = Field(default="Chat", max_length=120)
    greeting: str = Field(default="How can I help?", max_length=500)

    def model_post_init(self, __context: Any) -> None:
        if not self.path.startswith(CHAT_TRIGGER_PREFIX):
            raise ValueError(f"Chat path must start with '{CHAT_TRIGGER_PREFIX}'.")
        if not _PATH_RE.match(self.path):
            raise ValueError(f"Invalid chat path '{self.path}'.")


@register
class ChatTriggerNode(BaseNode[ChatTriggerParams]):
    node_type = "chat_trigger"
    display_name = "Chat Trigger"
    version = 1
    description = "Starts the workflow for each chat message."
    category = "Triggers"
    icon = "🗨️"
    parameters_schema = ChatTriggerParams
    input_handles: list[str] = []

    async def run(
        self,
        ctx: NodeContext,
        params: ChatTriggerParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        if not input_items:
            return NodeResult(output_items=[{
                "success": True, "message": "", "session_id": "", "history": [],
            }])
        output_items: list[dict[str, Any]] = []
        for item in input_items:
            if isinstance(item, dict) and "message" in item:
                output_items.append({"success": True, **item})
            else:
                output_items.append({
                    "success": True, "message": str(item), "session_id": "", "history": [],
                })
        return NodeResult(output_items=output_items)
