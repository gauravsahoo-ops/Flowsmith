"""Calendly connector implementing the ConnectorSDK interface."""

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
from app.providers.calendly import CalendlyProviderClient


class CalendlyConnectorParams(BaseModel):
    operation: str = Field(default="list_events")
    user_uri: str = ""
    event_uuid: str = ""
    count: int = Field(default=20, ge=1, le=100)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class CalendlyConnector(ConnectorSDK):
    connector_id = "calendly"
    display_name = "Calendly"
    description = "Work with Calendly event types and scheduled events."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = CalendlyProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["calendly"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("access_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = CalendlyConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Calendly payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("calendly") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_event_types":
                types = await self._provider.list_event_types(creds, str(raw.get("user_uri") or params.user_uri), timeout=timeout)
                return {"event_types": types}
            if op == "list_events":
                events = await self._provider.list_events(
                    creds, str(raw.get("user_uri") or params.user_uri),
                    int(raw.get("count") or params.count), timeout=timeout,
                )
                return {"events": events}
            if op == "get_event":
                return await self._provider.get_event(creds, str(raw.get("event_uuid") or params.event_uuid), timeout=timeout)
            if op == "cancel_event":
                return await self._provider.cancel_event(creds, str(raw.get("event_uuid") or params.event_uuid), timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Calendly operation '{operation}'.", retryable=False)

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_event_types", "list_events", "get_event", "cancel_event"]}}
