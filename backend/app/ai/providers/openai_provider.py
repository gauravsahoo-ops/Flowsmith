"""OpenAI and OpenAI-compatible Provider implementation.

Supports GPT-4o, GPT-4o-mini, o1, o3-mini, and compatible gateways (vLLM, LiteLLM, LM Studio).
Supports tool calling, JSON Schema structured outputs, and token streaming.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from app.ai.providers.base import BaseLLMProvider, LLMResponse, LLMStreamChunk, ToolCall


class OpenAIProvider(BaseLLMProvider):
    provider_name: str = "openai"

    def _prepare_request(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any],
        response_format: dict[str, Any] | None,
        api_key: str,
        base_url: str,
        extra_headers: dict[str, str] | None,
        stream: bool = False,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        endpoint = f"{base_url.rstrip('/')}/chat/completions" if base_url else "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}" if api_key else "",
        }
        if extra_headers:
            headers.update(extra_headers)

        payload: dict[str, Any] = {
            "model": model or "gpt-4o-mini",
            "messages": messages,
            "stream": stream,
        }
        # o1/o3-mini don't take temperature or use max_completion_tokens
        is_reasoning_model = any(model.startswith(prefix) for prefix in ("o1", "o3", "o4"))
        if not is_reasoning_model:
            payload["temperature"] = temperature
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
        elif max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        if response_format:
            payload["response_format"] = response_format

        return endpoint, headers, payload

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
        endpoint, headers, payload = self._prepare_request(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            api_key=api_key,
            base_url=base_url,
            extra_headers=extra_headers,
            stream=False,
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)

        if resp.status_code >= 400:
            raise RuntimeError(f"OpenAI error ({resp.status_code}): {resp.text[:400]}")

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}

        # Parse tool calls
        parsed_tools: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args_str = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except Exception:
                args = {"raw": args_str}
            parsed_tools.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))

        usage = data.get("usage") or {}
        return LLMResponse(
            content=msg.get("content") or "",
            tool_calls=parsed_tools,
            reasoning_content=msg.get("reasoning_content") or "",
            raw_response=data,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason", "stop"),
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
        endpoint, headers, payload = self._prepare_request(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            response_format=None,
            api_key=api_key,
            base_url=base_url,
            extra_headers=extra_headers,
            stream=True,
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            async with client.stream("POST", endpoint, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    err_text = await resp.aread()
                    raise RuntimeError(f"OpenAI stream error ({resp.status_code}): {err_text.decode('utf-8')[:400]}")

                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_obj = json.loads(data_str)
                    except Exception:
                        continue
                    delta = ((chunk_obj.get("choices") or [{}])[0]).get("delta") or {}
                    yield LLMStreamChunk(
                        delta_content=delta.get("content") or "",
                        delta_reasoning=delta.get("reasoning_content") or "",
                        tool_call_chunks=delta.get("tool_calls") or [],
                        finish_reason=((chunk_obj.get("choices") or [{}])[0]).get("finish_reason"),
                    )
