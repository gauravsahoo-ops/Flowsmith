"""Intercom connector implementing the ConnectorSDK interface."""

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
from app.providers.intercom import IntercomProviderClient


class IntercomConnectorParams(BaseModel):
    operation: str = Field(default="list_conversations")
    conversation_id: str = ""
    body_text: str = ""
    message_type: str = "comment"
    email: str = ""
    name: str = ""
    role: str = "user"
    field: str = "email"
    operator: str = "="
    value: str = ""
    per_page: int = Field(default=25, ge=1, le=150)
    starting_after: str = ""
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class IntercomConnector(ConnectorSDK):
    connector_id = "intercom"
    display_name = "Intercom"
    description = "Manage customer communications, reply to tickets, and search user profiles with Intercom."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = IntercomProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["intercom"]

    async def connect(self, config: dict[str, Any]) -> bool:
        token = str(config.get("access_token") or config.get("token") or "").strip()
        return bool(token)

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = IntercomConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Intercom payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("intercom") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        conversation_id = str(raw.get("conversation_id") or params.conversation_id or "").strip()
        body_text = str(raw.get("body_text") or params.body_text or "").strip()
        message_type = str(raw.get("message_type") or params.message_type or "comment").strip()
        email = str(raw.get("email") or params.email or "").strip()
        name = str(raw.get("name") or params.name or "").strip()
        role = str(raw.get("role") or params.role or "user").strip()
        per_page = int(raw.get("per_page") or params.per_page)
        starting_after = str(raw.get("starting_after") or params.starting_after or "").strip() or None

        try:
            if op == "list_conversations":
                return await self._provider.list_conversations(creds, per_page=per_page, starting_after=starting_after, timeout=timeout)

            if op == "get_conversation":
                if not conversation_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "conversation_id is required.", retryable=False)
                return await self._provider.get_conversation(creds, conversation_id, timeout=timeout)

            if op == "reply_conversation":
                if not conversation_id or not body_text:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "conversation_id and body_text are required.", retryable=False)
                return await self._provider.reply_conversation(creds, conversation_id, body_text, message_type=message_type, timeout=timeout)

            if op == "list_contacts":
                return await self._provider.list_contacts(creds, per_page=per_page, starting_after=starting_after, timeout=timeout)

            if op == "create_contact":
                return await self._provider.create_contact(creds, email=email or None, name=name or None, role=role, timeout=timeout)

            if op == "search_contacts":
                field = str(raw.get("field") or params.field or "email")
                operator = str(raw.get("operator") or params.operator or "=")
                value = str(raw.get("value") or params.value or "")
                if not value:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "value is required for search_contacts.", retryable=False)
                query = {"field": field, "operator": operator, "value": value}
                return await self._provider.search_contacts(creds, query, timeout=timeout)

        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Intercom {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Intercom operation '{operation}'.", retryable=False)
