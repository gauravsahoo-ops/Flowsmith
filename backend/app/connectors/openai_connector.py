"""OpenAI connector implementing the ConnectorSDK interface."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorCategory,
    ConnectorError,
    ConnectorErrorCode,
    ConnectorSDK,
    ConnectorStatus,
    make_connector_error,
)
from app.providers.openai import OpenAIProviderClient


class OpenAIConnectorParams(BaseModel):
    operation: str = Field(default="list_models")
    model: str = ""
    text: str = ""
    messages: str = ""
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1, le=128000)
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class OpenAIConnector(ConnectorSDK):
    connector_id = "openai"
    display_name = "OpenAI"
    description = "OpenAI models, embeddings, and chat completions."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = OpenAIProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["openai"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_key") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = OpenAIConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid OpenAI payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("openai") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_models":
                return await self._provider.list_models(creds, timeout=timeout)
            if op == "create_embedding":
                text = raw.get("text", params.text)
                return await self._provider.create_embedding(
                    creds, str(raw.get("model") or params.model),
                    text if isinstance(text, list) else str(text), timeout=timeout)
            if op == "chat_completion":
                raw_messages = raw.get("messages", params.messages)
                if isinstance(raw_messages, str):
                    try:
                        messages = json.loads(raw_messages)
                    except ValueError as exc:
                        raise make_connector_error(
                            ConnectorErrorCode.BAD_REQUEST,
                            "chat_completion messages must be a JSON array.", retryable=False) from exc
                else:
                    messages = raw_messages
                if not isinstance(messages, list):
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST,
                        "chat_completion messages must be a JSON array.", retryable=False)
                return await self._provider.chat_completion(
                    creds, str(raw.get("model") or params.model), messages,
                    float(raw.get("temperature", params.temperature)),
                    int(raw.get("max_tokens", params.max_tokens)), timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported OpenAI operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (model catalog); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_models", "create_embedding", "chat_completion"]}}
