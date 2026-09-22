"""Groq Provider implementation for ultra-low latency AI inference.

Supports Llama 3.3 70B, Llama 3.1 8B, DeepSeek R1 Distill, Mixtral.
Executes at 300-500+ tokens per second on Groq LPU hardware.
"""

from __future__ import annotations

from typing import Any

from app.ai.providers.openai_provider import OpenAIProvider


class GroqProvider(OpenAIProvider):
    provider_name: str = "groq"

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
        target_base = base_url or "https://api.groq.com/openai/v1"
        target_model = model or "llama-3.3-70b-versatile"

        return super()._prepare_request(
            messages,
            model=target_model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            api_key=api_key,
            base_url=target_base,
            extra_headers=extra_headers,
            stream=stream,
        )
