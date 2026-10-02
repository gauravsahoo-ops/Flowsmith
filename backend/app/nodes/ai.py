"""AI node (Phase 8): chat with an OpenAI-compatible model.

Features:
- `{{ }}` expressions in the prompt/system resolve against the incoming
  items (like every other node).
- `response_format=json` returns parsed JSON (fallback: raw text).
- `tools` enable a tool-calling loop (current_time, http_request,
  database_query — see app/ai/tools.py) with a bounded `max_turns`.

Requires an `llm` credential on the node; `http` / `database`
credentials are used by the matching tools when attached.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.ai.client import LLMError, chat_completion
from app.ai.tools import TOOLS, openai_tools, run_tool
from app.engine.errors import NodeExecutionError
from app.engine.node_base import NON_IDEMPOTENT, BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

AVAILABLE_TOOLS = sorted(TOOLS)


class AIParams(BaseModel):
    prompt: str = Field(min_length=1, description="The user prompt ({{ }} expressions supported).")
    system_message: str = Field(default="", description="Optional system prompt.")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    response_format: str = Field(default="text", pattern="^(text|json)$")
    max_turns: int = Field(default=8, ge=1, le=20, description="Max model/tool round trips.")
    tools: list[str] = Field(default_factory=list, description="Tools the model may call.")
    provider: str = Field(default="", description="Optional provider identifier (e.g. openai, anthropic, groq, etc.).")
    model: str = Field(default="", description="Selected model identifier.")


@register
class AINode(BaseNode[AIParams]):
    node_type = "ai"
    display_name = "AI"
    version = 1
    description = "Chat with an OpenAI-compatible model; optional tool calling."
    category = "AI"
    icon = "ai"
    parameters_schema = AIParams
    credential_types = ["llm", "http", "database"]
    # Every turn spends a model call (spec 35).
    idempotency = NON_IDEMPOTENT

    async def run(
        self,
        ctx: NodeContext,
        params: AIParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        raw_cred = ctx.credentials.get("llm")
        if not raw_cred:
            raise NodeExecutionError(
                "The AI node needs an 'llm' credential.",
                code="CREDENTIALS_REQUIRED", node_id="ai", retryable=False,
            )
        llm_cred = dict(raw_cred)
        if params.provider:
            llm_cred["provider"] = params.provider
        if params.model:
            llm_cred["model"] = params.model
        elif llm_cred.get("selected_model"):
            llm_cred["model"] = llm_cred["selected_model"]

        invalid = [t for t in params.tools if t not in TOOLS]
        if invalid:
            raise NodeExecutionError(
                f"Unknown tool(s): {', '.join(invalid)}. Available: {', '.join(AVAILABLE_TOOLS)}.",
                code="INVALID_TOOLS", node_id="ai", retryable=False,
            )

        tool_defs = openai_tools(params.tools) if params.tools else None
        messages: list[dict[str, Any]] = []
        if params.system_message:
            messages.append({"role": "system", "content": params.system_message})
        messages.append({"role": "user", "content": params.prompt})

        tool_calls_log: list[dict[str, Any]] = []
        turns = 0
        try:
            while turns < params.max_turns:
                turns += 1
                message = await chat_completion(
                    llm_cred,
                    messages,
                    tools=tool_defs,
                    temperature=params.temperature,
                    response_json=params.response_format == "json",
                    http_client=ctx.http_client,
                    max_tokens=2000,
                )
                content = message.get("content")
                calls = message.get("tool_calls") or []
                if not calls:
                    break
                assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
                if tool_defs is not None:
                    assistant_msg["tool_calls"] = calls
                messages.append(assistant_msg)
                for call in calls:
                    fn = call.get("function") or {}
                    name = fn.get("name") or ""
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    tool_calls_log.append({"tool": name, "arguments": args})
                    try:
                        result_text = await run_tool(ctx, name, args)
                    except Exception as exc:  # surface tool failures to the model
                        result_text = json.dumps({"error": str(exc)}, ensure_ascii=False)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id") or "",
                        "content": result_text,
                    })
            else:
                raise NodeExecutionError(
                    f"AI agent hit the {params.max_turns}-turn limit without a final answer.",
                    code="AI_MAX_TURNS", node_id="ai", retryable=False,
                )
        except LLMError as exc:
            raise NodeExecutionError(exc.message, code=exc.code, node_id="ai", retryable=False) from exc

        response_text = content or ""
        if params.response_format == "json":
            try:
                response_text = json.loads(response_text)
            except (ValueError, TypeError):
                pass
        return NodeResult(output_items=[{
            "response": response_text,
            "model": llm_cred.get("model", ""),
            "turns": turns,
            "tool_calls": tool_calls_log,
        }])
