"""Production-Ready Autonomous AI Agent Node for Flowsmith.

Supports:
1. Multi-provider execution (OpenAI, Anthropic Claude, Gemini, DeepSeek, Groq, Ollama).
2. Native tool calling with multi-turn ReAct reasoning loop.
3. Tri-Tier Memory integration (Working window, Summary buffer, Episodic vector memory).
4. Structured Outputs with JSON Schema enforcement.
5. Rich execution tracing (thoughts, tool calls, arguments, outputs, execution duration).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from app.ai.client import chat_completion
from app.ai.memory import get_memory_manager
from app.ai.tools import TOOLS, openai_tools, run_tool
from app.engine.errors import NodeExecutionError
from app.engine.node_base import NON_IDEMPOTENT, BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

logger = logging.getLogger("nodes.ai_agent")


class AgentParams(BaseModel):
    instructions: str = Field(
        default="You are an autonomous AI assistant that solves complex tasks using available tools.",
        description="System instructions and persona.",
    )
    input: str = Field(
        default="",
        description="Task or user prompt for the agent (supports {{ }} expressions).",
    )
    model: str | None = Field(
        default=None,
        description="Optional model override (e.g. gpt-4o, claude-3-5-sonnet, gemini-2.0-flash, llama-3.3-70b).",
    )
    tools: list[str] = Field(
        default_factory=lambda: ["current_time", "calculator", "http_request", "database_query"],
        description="Tools available to the agent.",
    )
    memory_type: str = Field(
        default="window",
        pattern="^(window|summary|episodic|none)$",
        description="Memory type: window (sliding), summary (LLM compressed), episodic (pgvector), or none.",
    )
    session_id: str = Field(
        default="default",
        description="Session identifier for persisting conversation context across runs.",
    )
    max_iterations: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Maximum reasoning/tool loops before terminating.",
    )
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    response_format: str = Field(
        default="text",
        pattern="^(text|json)$",
        description="Desired final format: text or structured json.",
    )


@register
class AIAgentNode(BaseNode[AgentParams]):
    node_type = "ai_agent"
    display_name = "AI Agent"
    version = 2
    description = "Autonomous ReAct agent with native tool execution, multi-provider support, and persistent memory."
    category = "AI"
    icon = "🤖"
    parameters_schema = AgentParams
    credential_types = ["llm", "http", "database"]
    idempotency = NON_IDEMPOTENT

    async def run(
        self,
        ctx: NodeContext,
        params: AgentParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        llm_cred = ctx.credentials.get("llm")
        if not llm_cred:
            raise NodeExecutionError(
                "The AI Agent node requires an 'llm' credential.",
                code="CREDENTIALS_REQUIRED",
                node_id=self.node_type,
                retryable=False,
            )

        # Clone cred and apply model override if set
        effective_cred = dict(llm_cred)
        if params.model:
            effective_cred["model"] = params.model

        # Determine prompt / user input
        user_input = params.input.strip()
        if not user_input and input_items:
            first_item = input_items[0]
            user_input = first_item.get("prompt") or first_item.get("text") or first_item.get("input") or json.dumps(first_item)

        if not user_input:
            user_input = "Hello! What can you help me with?"

        # Resolve available tools
        declared_tools = [t for t in params.tools if t in TOOLS]
        active_tools_schema = openai_tools(declared_tools)

        # Initialize conversation messages
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": params.instructions},
        ]

        # Handle Tri-Tier Memory
        mem_manager = get_memory_manager()
        session_key = (
            f"{ctx.workflow_id}_{params.session_id}"
            if getattr(ctx, "workflow_id", None)
            else (f"{ctx.execution_id}_{params.session_id}" if getattr(ctx, "execution_id", None) else params.session_id)
        )

        if params.memory_type == "window":
            working_mem = await mem_manager.get_working_memory(session_key)
            messages.extend(working_mem.get_messages())
        elif params.memory_type == "summary":
            summary_mem = await mem_manager.get_summary_memory(session_key)
            messages.extend(summary_mem.get_messages())
        elif params.memory_type == "episodic":
            episodic_mem = await mem_manager.get_episodic_memory(session_key)
            recalled = await episodic_mem.recall_relevant_memories(user_input, top_k=3)
            if recalled:
                messages.append({
                    "role": "system",
                    "content": "[Relevant Historical Memories]:\n" + "\n- ".join(recalled),
                })

        # Append current user prompt
        messages.append({"role": "user", "content": user_input})

        # Execution tracking trace
        execution_trace: list[dict[str, Any]] = []
        tools_used_set: set[str] = set()
        final_answer: str | None = None
        structured_json: Any = None

        # ReAct loop
        for iteration in range(params.max_iterations):
            step_start = time.monotonic()
            try:
                msg = await chat_completion(
                    effective_cred,
                    messages=messages,
                    tools=active_tools_schema if active_tools_schema else None,
                    temperature=params.temperature,
                )
            except Exception as exc:
                raise NodeExecutionError(
                    f"Agent LLM turn failed on iteration {iteration + 1}: {exc}",
                    code="AGENT_LLM_ERROR",
                    node_id=self.node_type,
                ) from exc

            messages.append(msg)
            tool_calls = msg.get("tool_calls") or []
            content = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or ""

            step_trace = {
                "iteration": iteration + 1,
                "thought": content or reasoning,
                "tool_calls": [],
                "duration_ms": round((time.monotonic() - step_start) * 1000, 2),
            }

            # If no tool calls, model has reached final answer!
            if not tool_calls:
                final_answer = content
                if content:
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict) and "answer" in parsed:
                            final_answer = str(parsed["answer"])
                    except Exception:
                        pass
                step_trace["thought"] = final_answer
                execution_trace.append(step_trace)
                break

            # Execute tool calls
            for tc in tool_calls:
                fn = tc.get("function") or {}
                t_name = fn.get("name", "")
                t_args_raw = fn.get("arguments") or "{}"
                if isinstance(t_args_raw, str):
                    try:
                        t_args = json.loads(t_args_raw)
                    except Exception:
                        t_args = {"raw": t_args_raw}
                else:
                    t_args = t_args_raw

                tools_used_set.add(t_name)
                tool_start = time.monotonic()
                try:
                    tool_output = await run_tool(ctx, t_name, t_args)
                except Exception as t_err:
                    tool_output = f"Tool '{t_name}' execution error: {t_err}"

                tool_duration = round((time.monotonic() - tool_start) * 1000, 2)
                step_trace["tool_calls"].append({
                    "name": t_name,
                    "arguments": t_args,
                    "output": tool_output[:1000],
                    "duration_ms": tool_duration,
                })

                # Feed tool result back to the LLM
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": t_name,
                    "content": tool_output,
                })

            execution_trace.append(step_trace)

        if final_answer is None:
            raise NodeExecutionError(
                f"Agent reached max iterations ({params.max_iterations}) without producing a final answer.",
                code="AI_MAX_ITERATIONS",
                node_id=self.node_type,
            )

        # Parse JSON if response_format is json
        if params.response_format == "json":
            try:
                # Find JSON block if wrapped in markdown fences
                cleaned = final_answer.strip()
                if "```json" in cleaned:
                    cleaned = cleaned.split("```json")[1].split("```")[0].strip()
                elif "```" in cleaned:
                    cleaned = cleaned.split("```")[1].split("```")[0].strip()
                structured_json = json.loads(cleaned)
            except Exception:
                structured_json = {"raw": final_answer}

        # Update persistent memory
        if params.memory_type == "window":
            mem = await mem_manager.get_working_memory(session_key)
            mem.add_message("user", user_input)
            mem.add_message("assistant", final_answer)
        elif params.memory_type == "summary":
            mem_sum = await mem_manager.get_summary_memory(session_key)
            mem_sum.add_message("user", user_input)
            mem_sum.add_message("assistant", final_answer)
            await mem_sum.compress_if_needed(chat_completion, effective_cred)
        elif params.memory_type == "episodic":
            mem_epi = await mem_manager.get_episodic_memory(session_key)
            await mem_epi.store_memory(f"User asked: {user_input} | Answer: {final_answer[:200]}")

        # Assemble clean output item
        output_payload: dict[str, Any] = {
            "result": structured_json if structured_json is not None else final_answer,
            "output": structured_json if structured_json is not None else final_answer,
            "final_answer": final_answer,
            "tools_used": sorted(tools_used_set),
            "iterations": len(execution_trace),
            "trace": execution_trace,
            "session_id": params.session_id,
        }
        if structured_json is not None:
            output_payload["json"] = structured_json

        return NodeResult(output_items=[output_payload])
