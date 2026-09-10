"""Twilio connector implementing the ConnectorSDK interface."""

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
from app.providers.twilio import TwilioProviderClient


class TwilioConnectorParams(BaseModel):
    operation: str = Field(default="send_sms")
    from_number: str = ""
    to_number: str = ""
    body: str = ""
    message_sid: str = ""
    limit: int = Field(default=20, ge=1, le=100)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class TwilioConnector(ConnectorSDK):
    connector_id = "twilio"
    display_name = "Twilio"
    description = "Send and inspect Twilio SMS messages."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = TwilioProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["twilio"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("account_sid") or "").strip() and str(config.get("auth_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = TwilioConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Twilio payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("twilio") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "send_sms":
                return await self._provider.send_sms(
                    creds, str(raw.get("from_number") or params.from_number),
                    str(raw.get("to_number") or params.to_number),
                    str(raw.get("body") or params.body), timeout=timeout,
                )
            if op == "list_messages":
                messages = await self._provider.list_messages(creds, int(raw.get("limit") or params.limit), timeout=timeout)
                return {"messages": messages}
            if op == "get_message":
                return await self._provider.get_message(creds, str(raw.get("message_sid") or params.message_sid), timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Twilio operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (account read, never sends); secret-safe failures."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["send_sms", "list_messages", "get_message"]}}
