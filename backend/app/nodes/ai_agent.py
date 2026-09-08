"""AI Agent node (Phase 12, spec 20): LLM decides which tools to call
in a loop (ReAct-style) until it reaches a final answer.

Unlike the `ai` chat node (single prompt → optional tool call), the
agent loops: LLM decides action → execute tool → observe → repeat
until the LLM returns a final answer.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from app.ai.client import chat_completion, LLMError
from app.ai.tools import TOOLS, openai_tools, run_tool
from app.engine.errors import NodeExecutionError
from app.engine.node_base import NON_IDEMPOTENT, BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class AgentParams(BaseModel):
    instructions: str = Field(
        min_length=1,
        description="System instructions for the agent (what it should do, how to use tools).",
    )
    input: str = Field(
        default="",
        description="Initial user message / task for the agent.",
    )
    max_iterations: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Max tool-calling iterations to prevent infinite loops.",
    )
    temperature: float = Field(default=0.1, ge=0, le=2)
    memory: bool = Field(
        default=True,
        description="Maintain conversation history across invocations.",
    )
    max_entries: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Max conversation history entries to retain when memory is enabled.",
    )


SYSTEM_PROMPT = """You are an autonomous agent that can use tools to accomplish tasks.

You have access to the following tools:
{tool_descriptions}

You operate in a loop:
1. Think about what to do next (your internal reasoning).
2. If you need to use a tool, respond with a JSON object:
   {{"action": "tool_name", "arguments": {{...}}}}
3. The tool will execute and return a result.
4. Repeat until you have enough information to give a final answer.
5. When done, respond with a JSON object:
   {{"action": "final", "answer": "your final answer here"}}

Important:
- Only call ONE tool per response.
- Use tools when you need external information or to perform actions.
- Be concise in your reasoning.
- The final answer should be a complete response to the original task."""


@register
class AIAgentNode(BaseNode[AgentParams]):
    node_type = "ai_agent"
    display_name = "AI Agent"
    version = 1
    description = "Autonomous agent that uses tools in a loop to complete tasks."
    category = "AI"
    icon = "🤖"
    parameters_schema = AgentParams
    credential_types = ["llm", "http", "database"]
    # LLM calls + tools spend money on every run (spec 35).
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
                "The AI Agent node needs an 'llm' credential.",
                code="CREDENTIALS_REQUIRED", node_id="ai_agent", retryable=False,
            )

        # Prepare tool definitions for the LLM
        tool_specs = openai_tools(None)  # all tools
        tool_descriptions = "\n".join(
            f"- {t['function']['name']}: {t['function']['description']}"
            for t in tool_specs
        )

        # Build initial messages
        system_prompt = SYSTEM_PROMPT.format(tool_descriptions=tool_descriptions)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Add input from params or from incoming items
        user_input = params.input
        if not user_input and input_items:
            # Use first input item as the task
            user_input = json.dumps(input_items[0], ensure_ascii=False)

        # Load conversation history from storage when memory is enabled
        history: list[dict[str, Any]] = []
        storage_key = f"{ctx.execution_id}:{ctx.node_id or 'ai_agent'}:history"
        if params.memory:
            history = await ctx.storage.get(storage_key, default=[])
            messages.extend(history)

        if user_input:
            messages.append({"role": "user", "content": user_input})

        # Agent loop
        final_answer = None
        for iteration in range(params.max_iterations):
            # Call LLM
            try:
                response = await chat_completion(
                    credential=llm_cred,
                    messages=messages,
                    tools=tool_specs,
                    temperature=params.temperature,
                )
            except LLMError as e:
                raise NodeExecutionError(
                    f"LLM error: {e.message}",
                    code=e.code, node_id="ai_agent", retryable=False,
                )

            choice = response
            content = choice.get("content")
            tool_calls = choice.get("tool_calls", [])

            # Add assistant message to history
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": content,
            }
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_msg)

            if tool_calls:
                # Execute each tool call
                for tc in tool_calls:
                    tool_name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError as e:
                        tool_result = f"Error parsing arguments: {e}"
                    else:
                        try:
                            tool_result = await run_tool(ctx, tool_name, args)
                        except Exception as e:
                            tool_result = f"Tool error: {e}"

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })
            else:
                # No tool calls - check if it's a final answer
                content = content or ""
                # Try multiple strategies to parse final answer
                final_answer = self._extract_final_answer(content)
                if final_answer is not None:
                    break
                # If no tool calls and no final format, treat content as final answer
                if content.strip():
                    final_answer = content.strip()
                    break
                # Otherwise continue (LLM might be stuck)

        if final_answer is None:
            raise NodeExecutionError(
                "Agent reached max iterations without a final answer.",
                code="AI_MAX_ITERATIONS", node_id="ai_agent", retryable=False,
            )

        # Persist conversation history for next invocation
        if params.memory:
            # Save everything after the system prompt
            new_entries = messages[1:]
            combined = history + new_entries
            # Trim to max_entries (keep most recent)
            if len(combined) > params.max_entries:
                combined = combined[-params.max_entries:]
            await ctx.storage.set(storage_key, combined, ttl=3600)

        return NodeResult(output_items=[{"result": final_answer}])

    @staticmethod
    def _extract_final_answer(content: str) -> str | None:
        """Extract final answer from LLM output using multiple strategies.

        Handles:
        - Standard JSON: {"action": "final", "answer": "..."}
        - JSON with escaped quotes/newlines in answer
        - Markdown code blocks wrapping JSON
        - Partial/malformed JSON
        """
        if not content or not content.strip():
            return None

        text = content.strip()

        # Strategy 1: Try direct JSON parse (handles escaped quotes correctly)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("action") == "final":
                answer = parsed.get("answer", "")
                if isinstance(answer, str) and answer:
                    return answer
        except (json.JSONDecodeError, AttributeError):
            pass

        # Strategy 2: Extract JSON from markdown code blocks
        code_block_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
        if code_block_match:
            try:
                parsed = json.loads(code_block_match.group(1).strip())
                if isinstance(parsed, dict) and parsed.get("action") == "final":
                    answer = parsed.get("answer", "")
                    if isinstance(answer, str) and answer:
                        return answer
            except (json.JSONDecodeError, AttributeError):
                pass

        # Strategy 3: Find JSON object in text using bracket matching
        brace_start = text.find('{')
        if brace_start != -1:
            depth = 0
            in_string = False
            escape_next = False
            for i in range(brace_start, len(text)):
                c = text[i]
                if escape_next:
                    escape_next = False
                    continue
                if c == '\\':
                    escape_next = True
                    continue
                if c == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[brace_start:i + 1]
                        try:
                            parsed = json.loads(candidate)
                            if isinstance(parsed, dict) and parsed.get("action") == "final":
                                answer = parsed.get("answer", "")
                                if isinstance(answer, str) and answer:
                                    return answer
                        except (json.JSONDecodeError, AttributeError):
                            pass
                        break

        # Strategy 4: Fallback regex for simple cases (answer without special chars)
        final_match = re.search(
            r'\{\s*"action"\s*:\s*"final"\s*,\s*"answer"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
            text,
        )
        if final_match:
            answer = final_match.group(1)
            # Unescape common JSON escapes
            answer = answer.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
            if answer:
                return answer

        return None