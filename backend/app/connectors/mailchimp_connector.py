"""Mailchimp connector implementing the ConnectorSDK interface."""

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
from app.providers.mailchimp import MailchimpProviderClient


class MailchimpConnectorParams(BaseModel):
    operation: str = Field(default="list_lists")
    list_id: str = ""
    email: str = ""
    status: str = "subscribed"
    limit: int = Field(default=25, ge=1, le=1000)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class MailchimpConnector(ConnectorSDK):
    connector_id = "mailchimp"
    display_name = "Mailchimp"
    description = "Manage Mailchimp audiences and contacts."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = MailchimpProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["mailchimp"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_key") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = MailchimpConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Mailchimp payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("mailchimp") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_lists":
                return await self._provider.list_lists(
                    creds, int(raw.get("limit") or params.limit), timeout=timeout)
            if op == "get_list":
                return await self._provider.get_list(creds, str(raw.get("list_id") or params.list_id), timeout=timeout)
            if op == "add_member":
                return await self._provider.add_member(
                    creds, str(raw.get("list_id") or params.list_id),
                    str(raw.get("email") or params.email),
                    str(raw.get("status") or params.status), timeout=timeout)
            if op == "get_member":
                return await self._provider.get_member(
                    creds, str(raw.get("list_id") or params.list_id),
                    str(raw.get("email") or params.email), timeout=timeout)
            if op == "update_member":
                fields = {"status": str(raw.get("status") or params.status)} if (raw.get("status") or params.status) else {}
                return await self._provider.update_member(
                    creds, str(raw.get("list_id") or params.list_id),
                    str(raw.get("email") or params.email), fields, timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Mailchimp operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (account root); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_lists", "get_list", "add_member", "get_member", "update_member"]}}
