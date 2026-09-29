"""Anthropic Claude provider client (Phase 39 Native AI Connector).

Integrates with Anthropic Messages API v1 (Claude 3.5 Sonnet, Haiku, Opus).
Supports:
- Messages generation with system prompt, temperature, max_tokens, and tool calling
- Token count introspection
- Safe HTTP client SSRF isolation
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.anthropic")
_extract_anthropic_error = json_error_message("error", "message")
ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProviderClient(BaseProviderClient):
    """Client for Anthropic Claude Messages API."""

    api_base = ANTHROPIC_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("Anthropic uses static API keys.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> str:
        api_key = str(creds.get("api_key") or creds.get("token") or "").strip()
        if not api_key:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Anthropic connector requires 'api_key'.",
                retryable=False,
            )
        return api_key

    async def request_anthropic(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        api_key = self._validate_creds(creds)
        url = f"{self.api_base}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }

        try:
            async with get_safe_http_client() as client:
                resp = await client.request(
                    method.upper(),
                    url,
                    headers=headers,
                    json=json_body if json_body else None,
                    timeout=timeout,
                )
        except httpx.TimeoutException as exc:
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"Anthropic request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Anthropic request failed: {exc}", retryable=True) from exc

        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "Anthropic API key is invalid.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Anthropic access forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "Anthropic rate limit reached.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Anthropic service unavailable: {resp.status_code}", retryable=True)
        if resp.status_code >= 400:
            msg = _extract_anthropic_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Anthropic API error: {msg}", retryable=False)

        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text, "status_code": resp.status_code}

    async def generate_message(
        self,
        creds: dict[str, Any],
        messages: List[Dict[str, Any]],
        *,
        model: str = "claude-3-5-sonnet-20241022",
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: List[Dict[str, Any]] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools

        res = await self.request_anthropic(creds, "POST", "messages", json_body=body, timeout=timeout)
        content_blocks = res.get("content", [])
        text_output = ""
        for b in content_blocks:
            if b.get("type") == "text":
                text_output += b.get("text", "")
        return {
            "id": res.get("id"),
            "model": res.get("model", model),
            "role": res.get("role", "assistant"),
            "content": text_output,
            "text": text_output,
            "raw_blocks": content_blocks,
            "usage": res.get("usage", {}),
            "stop_reason": res.get("stop_reason"),
        }

    async def count_tokens(
        self,
        creds: dict[str, Any],
        messages: List[Dict[str, Any]],
        *,
        model: str = "claude-3-5-sonnet-20241022",
        system: str = "",
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"model": model, "messages": messages}
        if system:
            body["system"] = system
        return await self.request_anthropic(creds, "POST", "messages/count_tokens", json_body=body, timeout=timeout)
