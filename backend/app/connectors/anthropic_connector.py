"""Anthropic Claude connector implementing the ConnectorSDK interface."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorCategory,
    ConnectorErrorCode,
    ConnectorSDK,
    ConnectorStatus,
    make_connector_error,
)
from app.providers.anthropic import AnthropicProviderClient


class AnthropicConnectorParams(BaseModel):
    operation: str = Field(default="generate_message")
    prompt: str = ""
    system: str = ""
    model: str = "claude-3-5-sonnet-20241022"
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    messages: list[dict[str, Any]] | None = None
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class AnthropicConnector(ConnectorSDK):
    connector_id = "anthropic"
    display_name = "Anthropic Claude"
    description = "Interact with Anthropic Claude LLMs for reasoning, transformation, and text generation."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = AnthropicProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["anthropic"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_key") or config.get("token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = AnthropicConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Anthropic payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("anthropic") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        prompt = str(raw.get("prompt") or params.prompt or "").strip()
        system = str(raw.get("system") or params.system or "").strip()
        model = str(raw.get("model") or params.model or "claude-3-5-sonnet-20241022").strip()

        messages = raw.get("messages") or params.messages
        if not messages and prompt:
            messages = [{"role": "user", "content": prompt}]

        try:
            if op == "generate_message":
                if not messages:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Prompt or messages list is required.", retryable=False)
                return await self._provider.generate_message(
                    creds, messages,
                    model=model,
                    system=system,
                    max_tokens=int(raw.get("max_tokens") or params.max_tokens),
                    temperature=float(raw.get("temperature") or params.temperature),
                    timeout=timeout,
                )
            if op == "count_tokens":
                if not messages:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Prompt or messages list is required.", retryable=False)
                return await self._provider.count_tokens(
                    creds, messages,
                    model=model,
                    system=system,
                    timeout=timeout,
                )
        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Anthropic {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Anthropic operation '{operation}'.", retryable=False)
