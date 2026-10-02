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

from app.ai.memory import get_memory_manager
from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from app.providers.redis_provider import RedisProviderClient

MAX_MESSAGES = 200
DEFAULT_TTL_SECONDS = 7 * 24 * 3600


class MemoryParams(BaseModel):
    operation: Literal[
        "push",
        "recall",
        "clear",
        "search",
        "set_entity",
        "get_entity",
        "set_note",
        "get_notes",
        "summary",
    ] = Field(
        default="recall",
        description="Memory operation: push, recall, clear, search, set_entity, get_entity, set_note, get_notes, or summary.",
    )
    session_id: str = Field(default="default", description="Session key within the workspace.")
    role: str = Field(default="user", description="Message role for push (user/assistant/system).")
    content: str = Field(default="", description="Message content, note text, or search query.")
    entity_key: str | None = Field(default=None, description="Entity key or scratchpad note key.")
    entity_val: Any = Field(default=None, description="Entity value for set_entity.")
    limit: int = Field(default=20, ge=1, le=MAX_MESSAGES, description="Messages or results to return on recall/search.")
    ttl_seconds: int = Field(default=DEFAULT_TTL_SECONDS, ge=60, le=90 * 24 * 3600)
    backend: Literal["auto", "redis", "local"] = Field(
        default="auto",
        description="Backend storage: auto (Redis if credential provided, otherwise local complete memory), redis, or local.",
    )


def _key(workspace_id: str | None, session_id: str) -> str:
    ws = (workspace_id or "personal").strip() or "personal"
    session = "".join(c for c in session_id.strip() or "default" if c.isalnum() or c in "-_") or "default"
    return f"mem:{ws}:{session}"


@register
class MemoryNode(BaseNode[MemoryParams]):
    node_type = "memory"
    display_name = "Memory"
    version = 2
    description = "Session chat & cognitive memory: push, recall, clear, search, entities, scratchpad, and summaries."
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
        key = _key(ctx.workspace_id, params.session_id)
        has_redis_cred = bool((ctx.credentials.get("redis") or {}).get("uri"))
        use_redis = (params.backend == "redis") or (params.backend == "auto" and has_redis_cred)

        # Standard Redis-backed chat memory operations
        if use_redis and params.operation in ("push", "recall", "clear"):
            provider = RedisProviderClient()
            creds = dict(ctx.credentials.get("redis") or {})

            if params.operation == "clear":
                await provider.delete(creds, key)
                return NodeResult(output_items=[{"cleared": True, "session_id": params.session_id, "backend": "redis"}])

            if params.operation == "push":
                content = params.content.strip()
                if not content:
                    first = (input_items or [{}])[0]
                    if isinstance(first, dict):
                        content = str(first.get("content") or first.get("text") or "")
                if not content:
                    raise NodeExecutionError(
                        "push needs content.",
                        code="MEMORY_EMPTY_PUSH",
                        node_id="memory",
                        retryable=False,
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
                return NodeResult(output_items=[{"pushed": True, "count": len(messages), "backend": "redis"}])

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
                output_items=[{**m, "session_id": params.session_id, "backend": "redis"} for m in window]
                or [{"session_id": params.session_id, "empty": True, "backend": "redis"}]
            )

        # Autonomous Complete Multi-Tier Memory (runs locally without Redis or external LLMs)
        mem_manager = get_memory_manager()
        complete_mem = await mem_manager.get_complete_memory(key)

        if params.operation == "clear":
            await mem_manager.clear_session(key)
            return NodeResult(output_items=[{"cleared": True, "session_id": params.session_id, "backend": "local_complete"}])

        if params.operation == "push":
            content = params.content.strip()
            if not content:
                first = (input_items or [{}])[0]
                if isinstance(first, dict):
                    content = str(first.get("content") or first.get("text") or "")
            if not content:
                raise NodeExecutionError(
                    "push needs content.",
                    code="MEMORY_EMPTY_PUSH",
                    node_id="memory",
                    retryable=False,
                )

            complete_mem.working.add_message(params.role, content)
            complete_mem.full_buffer.add_message(params.role, content)
            complete_mem.entities.extract_from_text(content)
            await complete_mem.episodic.store_memory(content)
            await mem_manager._persist_to_disk(key, complete_mem)
            return NodeResult(output_items=[{
                "pushed": True,
                "count": len(complete_mem.working.messages),
                "backend": "local_complete",
                "session_id": params.session_id,
            }])

        if params.operation == "recall":
            messages = complete_mem.working.get_messages()[-params.limit :]
            return NodeResult(
                output_items=[{**m, "session_id": params.session_id, "backend": "local_complete"} for m in messages]
                or [{"session_id": params.session_id, "empty": True, "backend": "local_complete"}]
            )

        if params.operation == "search":
            query = params.content.strip()
            if not query and input_items:
                first = input_items[0]
                query = str(first.get("query") or first.get("text") or first.get("content") or "")
            results = await complete_mem.search(query or "", top_k=params.limit)
            return NodeResult(output_items=[{
                "query": query,
                "results": results,
                "count": len(results),
                "session_id": params.session_id,
                "backend": "local_complete",
            }])

        if params.operation == "set_entity":
            k = params.entity_key or ""
            val = params.entity_val if params.entity_val is not None else params.content
            if not k and input_items:
                first = input_items[0]
                k = str(first.get("key") or first.get("entity_key") or "")
                if val is None or val == "":
                    val = first.get("value") or first.get("val") or first.get("content")
            if k:
                complete_mem.entities.set(k, val)
                await mem_manager._persist_to_disk(key, complete_mem)
            return NodeResult(output_items=[{
                "saved": bool(k),
                "key": k,
                "value": val,
                "all_entities": complete_mem.entities.get_all(),
                "session_id": params.session_id,
                "backend": "local_complete",
            }])

        if params.operation == "get_entity":
            k = params.entity_key or ""
            if not k and input_items:
                first = input_items[0]
                k = str(first.get("key") or first.get("entity_key") or "")
            if k:
                val = complete_mem.entities.get(k)
                return NodeResult(output_items=[{"key": k, "value": val, "found": val is not None, "session_id": params.session_id}])
            return NodeResult(output_items=[{"entities": complete_mem.entities.get_all(), "session_id": params.session_id}])

        if params.operation == "set_note":
            k = params.entity_key or f"note_{int(time.time())}"
            note_content = params.content.strip()
            if not note_content and input_items:
                first = input_items[0]
                note_content = str(first.get("content") or first.get("text") or "")
            complete_mem.scratchpad.set(k, note_content)
            await mem_manager._persist_to_disk(key, complete_mem)
            return NodeResult(output_items=[{"saved": True, "key": k, "content": note_content, "session_id": params.session_id}])

        if params.operation == "get_notes":
            notes = complete_mem.scratchpad.list_notes()
            return NodeResult(output_items=[{"notes": notes, "count": len(notes), "session_id": params.session_id}])

        if params.operation == "summary":
            sum_text = complete_mem.summary.get_summary()
            if not sum_text:
                sum_text = complete_mem.summary._deterministic_extract(complete_mem.working.get_messages())
            return NodeResult(output_items=[{"summary": sum_text, "session_id": params.session_id, "backend": "local_complete"}])

        return NodeResult(output_items=[{"error": f"Unknown operation {params.operation}"}])
