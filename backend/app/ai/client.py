"""Minimal OpenAI-compatible chat client (Phase 8).

Talks to any `/chat/completions` endpoint (OpenAI, Ollama, LM Studio,
vLLM, ...) using an `llm` credential. Tools use the standard OpenAI
function-calling contract. Everything is async so nodes can call it
directly on the worker loop; the API endpoints run it via the worker's
shared httpx client when one is provided.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.engine.errors import NodeExecutionError


class LLMError(Exception):
    """Provider returned an error."""

    def __init__(self, message: str, code: str = "LLM_ERROR") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_json_response_format(value: str) -> bool:
    return value == "json"


async def chat_completion(
    credential: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.2,
    response_json: bool = False,
    http_client: httpx.AsyncClient | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """One chat-completion round trip. Returns the assistant `message`
    object (content and/or tool calls) from `choices[0]`."""
    base_url = str(credential.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    api_key = credential.get("api_key") or ""
    model = credential.get("model") or "gpt-4o-mini"
    timeout = float(credential.get("timeout_s") or 60)

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if response_json:
        payload["response_format"] = {"type": "json_object"}
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(timeout))
    try:
        try:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                content=json.dumps(payload, ensure_ascii=False),
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM provider unreachable: {exc}", code="LLM_NETWORK_ERROR") from exc
    finally:
        if http_client is None:
            await client.aclose()

    if resp.status_code >= 400:
        _raise_provider_error(resp.status_code, resp.text, model)
    body = resp.json()
    choices = body.get("choices") or []
    if not choices:
        raise LLMError("LLM provider returned no choices.", code="LLM_EMPTY_RESPONSE")
    return choices[0].get("message") or {}


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


def tool_error(call_name: str, message: str) -> NodeExecutionError:
    return NodeExecutionError(
        f"AI tool '{call_name}' failed: {message}",
        code="AI_TOOL_ERROR",
    )
