"""Brevo connector implementing the ConnectorSDK interface."""

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
from app.providers.brevo import BrevoProviderClient


class BrevoConnectorParams(BaseModel):
    operation: str = Field(default="list_contacts")
    sender: str = ""
    to: str = ""
    subject: str = ""
    html: str = ""
    text: str = ""
    email: str = ""
    subscribed: bool = True
    limit: int = Field(default=25, ge=1, le=1000)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class BrevoConnector(ConnectorSDK):
    connector_id = "brevo"
    display_name = "Brevo"
    description = "Send Brevo transactional email and manage contacts."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = BrevoProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["brevo"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_key") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = BrevoConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Brevo payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("brevo") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "send_email":
                return await self._provider.send_email(
                    creds, str(raw.get("sender") or params.sender),
                    str(raw.get("to") or params.to),
                    str(raw.get("subject") or params.subject),
                    str(raw.get("html") or params.html),
                    str(raw.get("text") or params.text), timeout=timeout)
            if op == "list_contacts":
                return await self._provider.list_contacts(
                    creds, int(raw.get("limit") or params.limit), timeout=timeout)
            if op == "get_contact":
                return await self._provider.get_contact(
                    creds, str(raw.get("email") or params.email), timeout=timeout)
            if op == "create_contact":
                return await self._provider.create_contact(
                    creds, str(raw.get("email") or params.email), timeout=timeout)
            if op == "update_contact":
                subscribed = raw.get("subscribed", params.subscribed)
                return await self._provider.update_contact(
                    creds, str(raw.get("email") or params.email),
                    {"subscribed": bool(subscribed)}, timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Brevo operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (account info); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["send_email", "list_contacts", "get_contact", "create_contact", "update_contact"]}}
