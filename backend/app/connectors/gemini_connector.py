"""Google Gemini connector implementing the ConnectorSDK interface."""

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
from app.providers.gemini import GeminiProviderClient


class GeminiConnectorParams(BaseModel):
    operation: str = Field(default="generate_content")
    prompt: str = ""
    text: str = ""
    system_instruction: str = ""
    model: str = "gemini-1.5-flash"
    max_output_tokens: int = Field(default=2048, ge=1, le=8192)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    contents: list[dict[str, Any]] | None = None
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class GeminiConnector(ConnectorSDK):
    connector_id = "gemini"
    display_name = "Google Gemini"
    description = "Generate multimodal text, reasoning, and embeddings using Google Gemini AI models."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GeminiProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["gemini"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_key") or config.get("token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = GeminiConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Gemini payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("gemini") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        prompt = str(raw.get("prompt") or params.prompt or "").strip()
        system = str(raw.get("system_instruction") or raw.get("system") or params.system_instruction or "").strip()
        model = str(raw.get("model") or params.model or "gemini-1.5-flash").strip()

        contents = raw.get("contents") or params.contents
        if not contents and prompt:
            contents = [{"parts": [{"text": prompt}]}]

        try:
            if op == "generate_content":
                if not contents:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Prompt or contents list is required.", retryable=False)
                return await self._provider.generate_content(
                    creds, contents,
                    model=model,
                    system_instruction=system,
                    temperature=float(raw.get("temperature") or params.temperature),
                    max_output_tokens=int(raw.get("max_output_tokens") or params.max_output_tokens),
                    timeout=timeout,
                )
            if op == "embed_content":
                text = str(raw.get("text") or prompt or params.text or "").strip()
                if not text:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Text to embed is required.", retryable=False)
                return await self._provider.embed_content(
                    creds, text,
                    model=str(raw.get("model") or "text-embedding-004"),
                    timeout=timeout,
                )
            if op == "count_tokens":
                if not contents:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Prompt or contents list is required.", retryable=False)
                return await self._provider.count_tokens(
                    creds, contents,
                    model=model,
                    timeout=timeout,
                )
        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Gemini {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Gemini operation '{operation}'.", retryable=False)
