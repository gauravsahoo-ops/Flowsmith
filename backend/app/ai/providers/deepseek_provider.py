"""DeepSeek Provider implementation.

Supports DeepSeek-V3 (deepseek-chat) and DeepSeek-R1 (deepseek-reasoner).
Extracts native `reasoning_content` tokens for deep chain-of-thought display.
"""

from __future__ import annotations

from typing import Any

from app.ai.providers.openai_provider import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    provider_name: str = "deepseek"

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
        target_base = base_url or "https://api.deepseek.com"
        target_model = model or "deepseek-chat"

        # Note: deepseek-reasoner ignores temperature
        return super()._prepare_request(
            messages,
            model=target_model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools if target_model != "deepseek-reasoner" else None,  # R1 currently doesn't support tools
            tool_choice=tool_choice,
            response_format=response_format,
            api_key=api_key,
            base_url=target_base,
            extra_headers=extra_headers,
            stream=stream,
        )
