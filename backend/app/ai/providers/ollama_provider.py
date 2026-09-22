"""Ollama Provider implementation for 100% private on-premise local inference.

Connects to local or remote Ollama server (default: http://localhost:11434).
Supports Llama 3, Mistral, Qwen, DeepSeek-R1 locally with zero data egress.
"""

from __future__ import annotations

from typing import Any

from app.ai.providers.openai_provider import OpenAIProvider


class OllamaProvider(OpenAIProvider):
    provider_name: str = "ollama"

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
        raw_base = (base_url or "http://localhost:11434").rstrip("/")
        # Ensure /v1 endpoint for OpenAI compatible chat
        if not raw_base.endswith("/v1"):
            target_base = f"{raw_base}/v1"
        else:
            target_base = raw_base
        target_model = model or "llama3.2"

        return super()._prepare_request(
            messages,
            model=target_model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            api_key=api_key or "ollama",
            base_url=target_base,
            extra_headers=extra_headers,
            stream=stream,
        )
