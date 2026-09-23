"""Universal Multi-Provider Chat Client for Flowsmith AI.

Routes requests across OpenAI, Anthropic Claude, Google Gemini, DeepSeek,
Groq, and local Ollama instances with uniform tool-calling, retry logic,
streaming, and structured outputs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import httpx

from app.ai.providers import (
    BaseLLMProvider,
    LLMResponse,
    LLMStreamChunk,
    get_provider,
)
from app.engine.errors import NodeExecutionError

logger = logging.getLogger("ai.client")


class LLMError(Exception):
    """Provider returned an error."""

    def __init__(self, message: str, code: str = "LLM_ERROR") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_json_response_format(value: str) -> bool:
    return value in ("json", "json_object")


def _raise_provider_error(status: int, text: str, model: str) -> None:
    detail = text[:300]
    try:
        parsed = json.loads(text)
        detail = parsed.get("error", {}).get("message") or detail
    except (ValueError, AttributeError):
        pass
    raise LLMError(
        f"LLM request to '{model}' failed with {status}: {detail}",
        code="LLM_HTTP_ERROR",
    )


async def chat_completion(
    credential: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] = "auto",
    temperature: float = 0.2,
    response_json: bool = False,
    response_format: dict[str, Any] | None = None,
    http_client: httpx.AsyncClient | None = None,
    max_tokens: int | None = None,
    retries: int = 0,
    fallback_credential: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a chat-completion turn across configured provider.

    Returns the assistant `message` dictionary containing `role`, `content`,
    optional `tool_calls`, and optional `reasoning_content`.
    """
    prov_name = credential.get("provider")
    model = credential.get("model") or "gpt-4o-mini"
    api_key = credential.get("api_key") or ""
    base_url = str(credential.get("base_url") or "").rstrip("/")
    timeout_s = float(credential.get("timeout_s") or 60.0)

    # Route specialized non-OpenAI providers (Anthropic, Gemini) via provider classes
    if prov_name in ("anthropic", "gemini") or (prov_name is None and model.startswith(("claude", "gemini"))):
        fmt = response_format
        if response_json and not fmt:
            fmt = {"type": "json_object"}

        provider: BaseLLMProvider = get_provider(provider_name=prov_name, model=model)
        try:
            res: LLMResponse = await provider.chat(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                tool_choice=tool_choice,
                response_format=fmt,
                api_key=api_key,
                base_url=base_url,
                timeout_s=timeout_s,
            )
            msg_dict: dict[str, Any] = {
                "role": "assistant",
                "content": res.content,
            }
            if res.reasoning_content:
                msg_dict["reasoning_content"] = res.reasoning_content
            if res.has_tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                            if isinstance(tc.arguments, dict)
                            else str(tc.arguments),
                        },
                    }
                    for tc in res.tool_calls
                ]
            return msg_dict
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM provider unreachable: {exc}", code="LLM_NETWORK_ERROR") from exc
        except Exception as exc:
            raise LLMError(f"LLM request to '{model}' failed: {exc}", code="LLM_EXECUTION_ERROR") from exc

    # Default: Native OpenAI-compatible /chat/completions endpoint
    # (Covers OpenAI, Ollama, DeepSeek, Groq, OpenRouter, Mistral, LM Studio, vLLM, and unit test doubles)
    if not base_url:
        if prov_name == "ollama":
            base_url = "http://localhost:11434/v1"
        elif prov_name == "deepseek":
            base_url = "https://api.deepseek.com/v1"
        elif prov_name == "groq":
            base_url = "https://api.groq.com/openai/v1"
        elif prov_name in ("openrouter", "open_router"):
            base_url = "https://openrouter.ai/api/v1"
        elif prov_name == "mistral":
            base_url = "https://api.mistral.ai/v1"
        else:
            base_url = "https://api.openai.com/v1"

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    if response_json:
        payload["response_format"] = {"type": "json_object"}
    elif response_format:
        payload["response_format"] = response_format
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    last_exc: Exception | None = None
    delay = 1.0

    for attempt in range(retries + 1):
        client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_s))
        try:
            try:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    content=json.dumps(payload, ensure_ascii=False),
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < retries:
                    logger.warning("LLM HTTP error on attempt %d: %s; retrying...", attempt + 1, exc)
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                raise LLMError(f"LLM provider unreachable: {exc}", code="LLM_NETWORK_ERROR") from exc
        finally:
            if http_client is None:
                await client.aclose()

        if resp.status_code >= 400:
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                logger.warning(
                    "LLM provider returned status %d on attempt %d; retrying in %0.1fs...",
                    resp.status_code,
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
                continue
            _raise_provider_error(resp.status_code, resp.text, model)

        body = resp.json()
        choices = body.get("choices") or []
        if not choices:
            raise LLMError("LLM provider returned no choices.", code="LLM_EMPTY_RESPONSE")

        message = choices[0].get("message") or {}
        return message

    if fallback_credential:
        logger.info("Primary LLM model '%s' failed; attempting fallback model...", model)
        return await chat_completion(
            fallback_credential,
            messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            response_json=response_json,
            response_format=response_format,
            max_tokens=max_tokens,
            retries=0,
            fallback_credential=None,
        )

    raise LLMError(f"LLM request to '{model}' failed: {last_exc}", code="LLM_EXECUTION_ERROR") from last_exc


async def stream_chat_completion(
    credential: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> AsyncIterator[LLMStreamChunk]:
    """Stream token chunks from the designated provider."""
    prov_name = credential.get("provider")
    model = credential.get("model") or "gpt-4o-mini"
    api_key = credential.get("api_key") or ""
    base_url = credential.get("base_url") or ""
    timeout_s = float(credential.get("timeout_s") or 60.0)

    if not base_url:
        if prov_name == "ollama":
            base_url = "http://localhost:11434/v1"
        elif prov_name == "deepseek":
            base_url = "https://api.deepseek.com/v1"
        elif prov_name == "groq":
            base_url = "https://api.groq.com/openai/v1"
        elif prov_name in ("openrouter", "open_router"):
            base_url = "https://openrouter.ai/api/v1"
        elif prov_name == "mistral":
            base_url = "https://api.mistral.ai/v1"
        else:
            base_url = "https://api.openai.com/v1"

    provider: BaseLLMProvider = get_provider(provider_name=prov_name, model=model)

    async for chunk in provider.stream_chat(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        api_key=api_key,
        base_url=base_url,
        timeout_s=timeout_s,
    ):
        yield chunk


def tool_error(call_name: str, message: str) -> NodeExecutionError:
    return NodeExecutionError(
        f"AI tool '{call_name}' failed: {message}",
        code="AI_TOOL_ERROR",
    )
