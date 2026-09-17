"""Zendesk connector implementing the ConnectorSDK interface."""

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
from app.providers.zendesk import ZendeskProviderClient


class ZendeskConnectorParams(BaseModel):
    operation: str = Field(default="list_tickets")
    ticket_id: str = ""
    subject: str = ""
    comment: str = ""
    body: str = ""
    status: str = ""
    priority: str = ""
    limit: int = Field(default=25, ge=1, le=100)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class ZendeskConnector(ConnectorSDK):
    connector_id = "zendesk"
    display_name = "Zendesk"
    description = "Manage Zendesk support tickets and comments."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = ZendeskProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["zendesk"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = ZendeskConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Zendesk payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("zendesk") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_tickets":
                return await self._provider.list_tickets(
                    creds, int(raw.get("limit") or params.limit), timeout=timeout)
            if op == "get_ticket":
                return await self._provider.get_ticket(
                    creds, str(raw.get("ticket_id") or params.ticket_id), timeout=timeout)
            if op == "create_ticket":
                return await self._provider.create_ticket(
                    creds, str(raw.get("subject") or params.subject),
                    str(raw.get("comment") or params.comment),
                    str(raw.get("priority") or params.priority), timeout=timeout)
            if op == "update_ticket":
                fields = {k: str(raw.get(k) if raw.get(k) is not None else getattr(params, k))
                          for k in ("status", "priority")}
                fields = {k: v for k, v in fields.items() if v}
                return await self._provider.update_ticket(
                    creds, str(raw.get("ticket_id") or params.ticket_id), fields, timeout=timeout)
            if op == "add_comment":
                return await self._provider.add_comment(
                    creds, str(raw.get("ticket_id") or params.ticket_id),
                    str(raw.get("body") or params.body), timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Zendesk operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (session user); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_tickets", "get_ticket", "create_ticket", "update_ticket", "add_comment"]}}
