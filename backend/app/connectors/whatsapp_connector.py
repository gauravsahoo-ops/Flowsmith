"""WhatsApp connector implementing the ConnectorSDK interface."""

from __future__ import annotations

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
from app.providers.whatsapp import WhatsAppProviderClient


class WhatsAppConnectorParams(BaseModel):
    operation: str = Field(default="send_text")
    to: str = ""
    body: str = ""
    preview_url: bool = False
    template: str = ""
    language: str = "en_US"
    message_id: str = ""
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class WhatsAppConnector(ConnectorSDK):
    connector_id = "whatsapp"
    display_name = "WhatsApp"
    description = "Send WhatsApp Business Cloud API text and template messages."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = WhatsAppProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["whatsapp"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("access_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = WhatsAppConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid WhatsApp payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("whatsapp") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "send_text":
                return await self._provider.send_text(
                    creds, str(raw.get("to") or params.to),
                    str(raw.get("body") or params.body),
                    bool(raw.get("preview_url", params.preview_url)), timeout=timeout,
                )
            if op == "send_template":
                return await self._provider.send_template(
                    creds, str(raw.get("to") or params.to),
                    str(raw.get("template") or params.template),
                    str(raw.get("language") or params.language), timeout=timeout,
                )
            if op == "get_message":
                return await self._provider.get_message(
                    creds, str(raw.get("message_id") or params.message_id), timeout=timeout,
                )
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported WhatsApp operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (verified_name); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["send_text", "send_template", "get_message"]}}
