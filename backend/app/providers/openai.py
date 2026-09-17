"""OpenAI provider client.

OpenAI REST API (or any OpenAI-compatible base URL) with Bearer API key.
Ops: list models, create embeddings, chat completion. 429/5xx retryable.
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error
from app.security.safe_http_client import get_safe_http_client

OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"


def _auth(creds: dict) -> tuple[str, str]:
    token = str((creds or {}).get("api_key") or "").strip()
    base = str((creds or {}).get("base_url") or OPENAI_DEFAULT_BASE).strip().rstrip("/")
    if not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "OpenAI connector needs an 'openai' credential with api_key.",
            retryable=False,
        )
    return token, base


def _raise(status: int, body: str, what: str, payload: Any = None) -> None:
    detail = ""
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and err.get("message"):
            detail = f": {str(err['message'])[:200]}"
        elif isinstance(err, str):
            detail = f": {err[:200]}"
    if status < 400:
        return
    if status == 401:
        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f"OpenAI auth failed during {what}{detail}.", retryable=False)
    if status == 403:
        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f"OpenAI forbade {what}{detail}.", retryable=False)
    if status == 404:
        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f"OpenAI resource missing during {what}{detail}.", retryable=False)
    if status == 429:
        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f"OpenAI rate limited during {what}{detail}.", retryable=True)
    if status >= 500:
        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"OpenAI unavailable during {what}{detail}.", retryable=True)
    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"OpenAI rejected {what}{detail or ': ' + body[:200]}.", retryable=False)


class OpenAIProviderClient:
    async def test_connection(self, creds: dict) -> dict:
        """Cheap live probe for the credential Test button (model catalog)."""
        data = await self.list_models(creds)
        n = len(data.get("data", []) or []) if isinstance(data, dict) else 0
        return {"ok": True, "message": f"Connected ({n} models available)."} if n else {"ok": True, "message": "Connected."}

    async def _post(self, creds: dict, path: str, body: dict[str, Any], what: str, timeout: float = 60.0) -> dict:
        token, base = _auth(creds)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        org = str((creds or {}).get("organization") or "").strip()
        if org:
            headers["OpenAI-Organization"] = org
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "POST", f"{base}{path}", headers=headers, json=body, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"OpenAI unreachable during {what}: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, what, payload)
        return payload if isinstance(payload, dict) else {}

    async def list_models(self, creds: dict, timeout: float = 30.0) -> dict:
        token, base = _auth(creds)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "GET", f"{base}/models",
                    headers={"Authorization": f"Bearer {token}"}, timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"OpenAI unreachable during list_models: {exc}", retryable=True,
            ) from exc
        try:
            payload = response.json()
        except Exception:
            payload = {}
        _raise(response.status_code, response.text, "list_models", payload)
        return payload if isinstance(payload, dict) else {}

    async def create_embedding(
        self, creds: dict, model: str, text: str | list[str], timeout: float = 60.0,
    ) -> dict:
        if not str(model or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_embedding needs a model.", retryable=False)
        if not text or (isinstance(text, str) and not text.strip()):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_embedding needs input text.", retryable=False)
        return await self._post(creds, "/embeddings", {"model": model, "input": text}, "create_embedding", timeout)

    async def chat_completion(
        self, creds: dict, model: str, messages: list[dict[str, Any]],
        temperature: float = 0.7, max_tokens: int = 1024, timeout: float = 90.0,
    ) -> dict:
        if not str(model or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "chat_completion needs a model.", retryable=False)
        if not messages:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "chat_completion needs messages.", retryable=False)
        return await self._post(
            creds, "/chat/completions",
            {"model": model, "messages": messages,
             "temperature": float(temperature), "max_tokens": int(max_tokens)},
            "chat_completion", timeout,
        )
