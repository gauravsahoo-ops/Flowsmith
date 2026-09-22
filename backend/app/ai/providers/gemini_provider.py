"""Google Gemini Provider implementation.

Supports Gemini 2.0 Flash, Gemini 1.5 Pro, Gemini 1.5 Flash.
Supports native Google AI Studio REST format with function calling and system instructions.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from app.ai.providers.base import BaseLLMProvider, LLMResponse, LLMStreamChunk, ToolCall


class GeminiProvider(BaseLLMProvider):
    provider_name: str = "gemini"

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI tool schema into Gemini functionDeclarations."""
        declarations = []
        for t in tools:
            if "function" in t:
                fn = t["function"]
                declarations.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
                })
            elif "name" in t:
                declarations.append(t)
        return [{"functionDeclarations": declarations}] if declarations else []

    def _format_messages(self, messages: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Convert standard messages into Gemini contents and system_instruction."""
        system_instruction = None
        contents: list[dict[str, Any]] = []

        for m in messages:
            role = m.get("role")
            content = m.get("content") or ""
            if role == "system":
                system_instruction = {"parts": [{"text": str(content)}]}
            elif role == "assistant" and m.get("tool_calls"):
                parts: list[dict[str, Any]] = []
                if content:
                    parts.append({"text": str(content)})
                for tc in m["tool_calls"]:
                    fn = tc.get("function") or {}
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    parts.append({
                        "functionCall": {
                            "name": fn.get("name", ""),
                            "args": args,
                        }
                    })
                contents.append({"role": "model", "parts": parts})
            elif role == "tool":
                tool_name = m.get("name") or "tool_result"
                contents.append({
                    "role": "function",
                    "parts": [{
                        "functionResponse": {
                            "name": tool_name,
                            "response": {"output": str(content)},
                        }
                    }]
                })
            else:
                gemini_role = "model" if role == "assistant" else "user"
                contents.append({"role": gemini_role, "parts": [{"text": str(content)}]})

        return system_instruction, contents

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
        model_clean = model or "gemini-2.0-flash"
        if base_url:
            endpoint = f"{base_url.rstrip('/')}/models/{model_clean}:generateContent"
        else:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_clean}:generateContent?key={api_key}"

        system_instruction, contents = self._format_messages(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            }
        }
        if max_tokens:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        if tools:
            payload["tools"] = self._convert_tools(tools)
        if response_format and response_format.get("type") in ("json_object", "json"):
            payload["generationConfig"]["responseMimeType"] = "application/json"

        headers = {"Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)

        if resp.status_code >= 400:
            raise RuntimeError(f"Gemini error ({resp.status_code}): {resp.text[:400]}")

        data = resp.json()
        candidates = data.get("candidates") or [{}]
        first_candidate = candidates[0] if candidates else {}
        parts = (first_candidate.get("content") or {}).get("parts") or []

        content_text = ""
        tool_calls: list[ToolCall] = []

        for p in parts:
            if "text" in p:
                content_text += p["text"]
            if "functionCall" in p:
                fc = p["functionCall"]
                tool_calls.append(ToolCall(
                    id=fc.get("name", "tool_call"),
                    name=fc.get("name", ""),
                    arguments=fc.get("args") or {},
                ))

        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            raw_response=data,
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
            finish_reason=first_candidate.get("finishReason", "STOP"),
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
        # Fallback to chat for streaming if stream endpoint is not used
        res = await self.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            api_key=api_key,
            base_url=base_url,
            timeout_s=timeout_s,
            extra_headers=extra_headers,
        )
        yield LLMStreamChunk(delta_content=res.content, finish_reason=res.finish_reason)
