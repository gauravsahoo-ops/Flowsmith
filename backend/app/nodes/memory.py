"""Memory node (Batch C, original implementation).

Session-scoped chat memory on top of the shared Redis provider
(`RedisProviderClient.get/set`): push messages, recall the last N,
or clear a session. Keys are namespaced per workspace (`mem:{ws}:{session}`)
with a TTL so stale sessions expire on their own.

v1 note: push is read-modify-write; concurrent pushes to one session
may interleave. Single-writer agent loops (the normal case) are fine.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from app.providers.redis_provider import RedisProviderClient

MAX_MESSAGES = 200
DEFAULT_TTL_SECONDS = 7 * 24 * 3600


class MemoryParams(BaseModel):
    operation: Literal["push", "recall", "clear"] = Field(default="recall")
    session_id: str = Field(default="default", description="Session key within the workspace.")
    role: str = Field(default="user", description="Message role for push (user/assistant/system).")
    content: str = Field(default="", description="Message content for push.")
    limit: int = Field(default=20, ge=1, le=MAX_MESSAGES, description="Messages to return on recall.")
    ttl_seconds: int = Field(default=DEFAULT_TTL_SECONDS, ge=60, le=90 * 24 * 3600)


def _key(workspace_id: str | None, session_id: str) -> str:
    ws = (workspace_id or "personal").strip() or "personal"
    session = "".join(c for c in session_id.strip() or "default" if c.isalnum() or c in "-_") or "default"
    return f"mem:{ws}:{session}"


@register
class MemoryNode(BaseNode[MemoryParams]):
    node_type = "memory"
    display_name = "Memory"
    version = 1
    description = "Session chat memory: push, recall, or clear messages."
    category = "AI"
    icon = "memory"
    credential_types = ["redis"]
    parameters_schema = MemoryParams
    idempotency = "conditionally_idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: MemoryParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        provider = RedisProviderClient()
        creds = dict(ctx.credentials.get("redis") or {})
        key = _key(ctx.workspace_id, params.session_id)

        if params.operation == "clear":
            await provider.delete(creds, key)
            return NodeResult(output_items=[{"cleared": True, "session_id": params.session_id}])

        if params.operation == "push":
            content = params.content.strip()
            if not content:
                # Fall back to first input item text.
                first = (input_items or [{}])[0]
                if isinstance(first, dict):
                    content = str(first.get("content") or first.get("text") or "")
            if not content:
                raise NodeExecutionError(
                    "push needs content.",
                    code="MEMORY_EMPTY_PUSH", node_id="memory", retryable=False,
                )
            current = await provider.get(creds, key)
            try:
                messages = json.loads(current.get("value", "[]") or "[]")
                if not isinstance(messages, list):
                    messages = []
            except Exception:
                messages = []
            messages.append({"role": params.role, "content": content, "ts": int(time.time())})
            messages = messages[-MAX_MESSAGES:]
            await provider.set(creds, key, json.dumps(messages), ttl_seconds=params.ttl_seconds)
            return NodeResult(output_items=[{"pushed": True, "count": len(messages)}])

        # recall
        current = await provider.get(creds, key)
        try:
            messages = json.loads(current.get("value", "[]") or "[]")
            if not isinstance(messages, list):
                messages = []
        except Exception:
            messages = []
        window = messages[-params.limit :]
        return NodeResult(
            output_items=[{**m, "session_id": params.session_id} for m in window]
            or [{"session_id": params.session_id, "empty": True}]
        )
