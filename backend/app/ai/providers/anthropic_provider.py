"""Anthropic Claude Provider implementation.

Supports Claude 3.5 Sonnet, Claude 3.5 Haiku, Claude 3 Opus.
Supports native tool calling (converting from/to OpenAI schema), thinking blocks, and streaming.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from app.ai.providers.base import BaseLLMProvider, LLMResponse, LLMStreamChunk, ToolCall


class AnthropicProvider(BaseLLMProvider):
    provider_name: str = "anthropic"

    def _convert_tools(self, openai_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI tool schema (`type="function"`) to Anthropic (`input_schema`)."""
        anthropic_tools = []
        for t in openai_tools:
            if "function" in t:
                fn = t["function"]
                anthropic_tools.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })
            elif "name" in t:
                anthropic_tools.append(t)
        return anthropic_tools

    def _format_messages(self, messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        """Extract top-level system prompt and format remaining messages for Anthropic."""
        system_prompt = ""
        formatted = []

        for m in messages:
            role = m.get("role")
            content = m.get("content") or ""
            if role == "system":
                if system_prompt:
                    system_prompt += "\n\n" + str(content)
                else:
                    system_prompt = str(content)
            elif role == "tool":
                # Convert OpenAI tool result message to Anthropic tool_result block
                tool_use_id = m.get("tool_call_id", "")
                formatted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": str(content),
                    }],
                })
            elif role == "assistant" and m.get("tool_calls"):
                # Assistant emitted tool calls
                content_blocks: list[dict[str, Any]] = []
                if content:
                    content_blocks.append({"type": "text", "text": str(content)})
                for tc in m["tool_calls"]:
                    fn = tc.get("function") or {}
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {"raw": args}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": args,
                    })
                formatted.append({"role": "assistant", "content": content_blocks})
            else:
                formatted.append({
                    "role": "assistant" if role == "assistant" else "user",
                    "content": content,
                })

        return system_prompt, formatted

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        response_format: dict[str, Any] | None = None,
        api_key: str = "",
        base_url: str = "",
        timeout_s: float = 60.0,
        extra_headers: dict[str, str] | None = None,
    ) -> LLMResponse:
        endpoint = f"{base_url.rstrip('/')}/v1/messages" if base_url else "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        if extra_headers:
            headers.update(extra_headers)

        system_prompt, anthropic_messages = self._format_messages(messages)
        payload: dict[str, Any] = {
            "model": model or "claude-3-5-sonnet-20241022",
            "messages": anthropic_messages,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if tools:
            payload["tools"] = self._convert_tools(tools)
            if tool_choice == "any":
                payload["tool_choice"] = {"type": "any"}
            elif isinstance(tool_choice, dict):
                payload["tool_choice"] = tool_choice

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)

        if resp.status_code >= 400:
            raise RuntimeError(f"Anthropic error ({resp.status_code}): {resp.text[:400]}")

        data = resp.json()
        content_text = ""
        reasoning_text = ""
        tool_calls: list[ToolCall] = []

        for block in data.get("content") or []:
            b_type = block.get("type")
            if b_type == "text":
                content_text += block.get("text", "")
            elif b_type == "thinking":
                reasoning_text += block.get("thinking", "")
            elif b_type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input") or {},
                ))

        usage = data.get("usage") or {}
        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            reasoning_content=reasoning_text,
            raw_response=data,
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            finish_reason=data.get("stop_reason", "end_turn"),
        )

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        api_key: str = "",
        base_url: str = "",
        timeout_s: float = 60.0,
        extra_headers: dict[str, str] | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        endpoint = f"{base_url.rstrip('/')}/v1/messages" if base_url else "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        if extra_headers:
            headers.update(extra_headers)

        system_prompt, anthropic_messages = self._format_messages(messages)
        payload: dict[str, Any] = {
            "model": model or "claude-3-5-sonnet-20241022",
            "messages": anthropic_messages,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
            "stream": True,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if tools:
            payload["tools"] = self._convert_tools(tools)

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            async with client.stream("POST", endpoint, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    err_text = await resp.aread()
                    raise RuntimeError(f"Anthropic stream error ({resp.status_code}): {err_text.decode('utf-8')[:400]}")

                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    try:
                        event = json.loads(data_str)
                    except Exception:
                        continue
                    ev_type = event.get("type")
                    if ev_type == "content_block_delta":
                        delta = event.get("delta") or {}
                        d_type = delta.get("type")
                        if d_type == "text_delta":
                            yield LLMStreamChunk(delta_content=delta.get("text", ""))
                        elif d_type == "thinking_delta":
                            yield LLMStreamChunk(delta_reasoning=delta.get("thinking", ""))
                    elif ev_type == "message_stop":
                        yield LLMStreamChunk(finish_reason="end_turn")
