"""Google Gemini provider client (Phase 39 Native AI Connector).

Integrates with Google Gemini Generative Language REST API v1beta.
Supports:
- generateContent for Gemini 1.5 Pro, Flash, and 2.0 Flash
- embedContent for text-embedding-004
- countTokens endpoint
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import BaseProviderClient, json_error_message
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("providers.gemini")
_extract_gemini_error = json_error_message("error", "message")
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProviderClient(BaseProviderClient):
    """Client for Google Gemini REST APIs."""

    api_base = GEMINI_API_BASE

    def _client_id_secret(self) -> tuple[str, str]:
        return "", ""

    async def _refresh(self, http_client: Any, refresh_token: str) -> tuple[str, float]:
        raise NotImplementedError("Gemini uses Google API keys or service account tokens.")

    @staticmethod
    def _validate_creds(creds: dict[str, Any]) -> str:
        api_key = str(creds.get("api_key") or creds.get("token") or "").strip()
        if not api_key:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Google Gemini connector requires an 'api_key'.",
                retryable=False,
            )
        return api_key

    async def request_gemini(
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
            "x-goog-api-key": api_key,
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
            raise make_connector_error(ConnectorErrorCode.TIMEOUT, f"Google Gemini request timed out: {exc}", retryable=True) from exc
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Google Gemini request failed: {exc}", retryable=True) from exc

        if resp.status_code == 400:
            msg = _extract_gemini_error(resp) or resp.text[:200]
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Google Gemini bad request: {msg}", retryable=False)
        if resp.status_code == 401:
            raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, "Google Gemini API key is invalid.", retryable=False)
        if resp.status_code == 403:
            raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"Google Gemini access forbidden: {resp.text[:200]}", retryable=False)
        if resp.status_code == 429:
            raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, "Google Gemini quota or rate limit exceeded.", retryable=True)
        if resp.status_code >= 500:
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Google Gemini server error: {resp.status_code}", retryable=True)

        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text, "status_code": resp.status_code}

    async def generate_content(
        self,
        creds: dict[str, Any],
        contents: List[Dict[str, Any]],
        *,
        model: str = "gemini-1.5-flash",
        system_instruction: str = "",
        temperature: float = 0.7,
        max_output_tokens: int = 2048,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        path = f"models/{model}:generateContent"
        res = await self.request_gemini(creds, "POST", path, json_body=body, timeout=timeout)

        candidates = res.get("candidates", [])
        text_out = ""
        if candidates and "content" in candidates[0]:
            parts = candidates[0]["content"].get("parts", [])
            for p in parts:
                if "text" in p:
                    text_out += p["text"]

        return {
            "model": model,
            "text": text_out,
            "candidates": candidates,
            "usage_metadata": res.get("usageMetadata", {}),
        }

    async def embed_content(
        self,
        creds: dict[str, Any],
        text: str,
        *,
        model: str = "text-embedding-004",
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body = {
            "model": f"models/{model}",
            "content": {
                "parts": [{"text": text}]
            }
        }
        path = f"models/{model}:embedContent"
        res = await self.request_gemini(creds, "POST", path, json_body=body, timeout=timeout)
        embedding = res.get("embedding", {})
        return {
            "model": model,
            "values": embedding.get("values", []),
        }

    async def count_tokens(
        self,
        creds: dict[str, Any],
        contents: List[Dict[str, Any]],
        *,
        model: str = "gemini-1.5-flash",
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body = {"contents": contents}
        path = f"models/{model}:countTokens"
        return await self.request_gemini(creds, "POST", path, json_body=body, timeout=timeout)
