"""Freshdesk connector implementing the ConnectorSDK interface."""

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
from app.providers.freshdesk import FreshdeskProviderClient


class FreshdeskConnectorParams(BaseModel):
    operation: str = Field(default="list_tickets")
    ticket_id: str = ""
    subject: str = ""
    description: str = ""
    email: str = ""
    body: str = ""
    status: int | None = None
    priority: int | None = None
    limit: int = Field(default=25, ge=1, le=100)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class FreshdeskConnector(ConnectorSDK):
    connector_id = "freshdesk"
    display_name = "Freshdesk"
    description = "Manage Freshdesk support tickets and notes."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = FreshdeskProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["freshdesk"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = FreshdeskConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Freshdesk payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("freshdesk") or {}
        raw = payload or {}

        def _pick(key: str, default: Any = None) -> Any:
            value = raw.get(key, getattr(params, key, default))
            return default if value is None else value

        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_tickets":
                return await self._provider.list_tickets(
                    creds, int(_pick("limit", 25)), timeout=timeout)
            if op == "get_ticket":
                return await self._provider.get_ticket(
                    creds, str(_pick("ticket_id", "")), timeout=timeout)
            if op == "create_ticket":
                return await self._provider.create_ticket(
                    creds, str(_pick("subject", "")), str(_pick("description", "")),
                    str(_pick("email", "")), int(_pick("priority", 1) or 1), timeout=timeout)
            if op == "update_ticket":
                fields = {k: int(v) for k, v in
                          (("status", _pick("status")), ("priority", _pick("priority")))
                          if v is not None}
                return await self._provider.update_ticket(
                    creds, str(_pick("ticket_id", "")), fields, timeout=timeout)
            if op == "add_note":
                return await self._provider.add_note(
                    creds, str(_pick("ticket_id", "")),
                    str(_pick("body", "")), timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Freshdesk operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (agent profile); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_tickets", "get_ticket", "create_ticket", "update_ticket", "add_note"]}}
