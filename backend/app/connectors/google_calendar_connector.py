"""Google Calendar connector implementing the ConnectorSDK interface.

Operation layer mapping connector operations (list_events, get_event,
create_event, update_event, delete_event) onto the
GoogleCalendarProviderClient, which owns all Google HTTP concerns.

Credentials arrive via context["credentials"]["google_calendar"].
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorSDK,
    ConnectorError,
    ConnectorCategory,
    ConnectorStatus,
    ConnectorErrorCode,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations
from app.providers.google_calendar import GoogleCalendarProviderClient

logger = logging.getLogger(__name__)


class GoogleCalendarConnectorParams(BaseModel):
    """Parameters for a Google Calendar connector operation."""

    operation: str = Field(default="list_events")
    calendar_id: str = Field(default="primary", description="'primary' or a specific calendar id.")
    event_id: str = Field(default="", description="Event id (get/update/delete).")
    event: dict[str, Any] = Field(default_factory=dict, description="Event resource (create/update).")
    time_min: str = Field(default="", description="RFC3339 lower bound (list_events).")
    time_max: str = Field(default="", description="RFC3339 upper bound (list_events).")
    max_results: int = Field(default=25, ge=1, le=250)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class GoogleCalendarConnector(ConnectorSDK, ConnectorOperations):
    """Google Calendar connector - events CRUD via Calendar API v3."""

    connector_id = "google_calendar"
    display_name = "Google Calendar"
    description = "List and manage events on a Google Calendar."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GoogleCalendarProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["google_calendar"]

    async def connect(self, config: dict[str, Any]) -> bool:
        if not config.get("refresh_token"):
            return False
        self.status = ConnectorStatus.CONNECTED
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._provider.reset()
        self._metadata.clear()

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = GoogleCalendarConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid Google Calendar payload: {exc}",
                retryable=False,
            ) from exc

        creds = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("google_calendar") or {}

        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        try:
            if op == "list_events":
                return await self._provider.list_events(
                    creds, params.calendar_id,
                    time_min=params.time_min or None,
                    time_max=params.time_max or None,
                    max_results=params.max_results,
                    timeout=params.timeout_seconds,
                )
            if op == "get_event":
                rid = self._require(payload.get("event_id"), "operation=get_event requires event_id.")
                return await self._provider.get_event(creds, params.calendar_id, rid, timeout=params.timeout_seconds)
            if op == "create_event":
                event = payload.get("event") or params.event
                if not isinstance(event, dict) or not event:
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST,
                        "operation=create_event requires an event map.",
                        retryable=False,
                    )
                return await self._provider.create_event(creds, params.calendar_id, event, timeout=params.timeout_seconds)
            if op == "update_event":
                rid = self._require(payload.get("event_id"), "operation=update_event requires event_id.")
                event = payload.get("event") or params.event
                if not isinstance(event, dict) or not event:
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST,
                        "operation=update_event requires an event map.",
                        retryable=False,
                    )
                return await self._provider.update_event(creds, params.calendar_id, rid, event, timeout=params.timeout_seconds)
            if op == "delete_event":
                rid = self._require(payload.get("event_id"), "operation=delete_event requires event_id.")
                return await self._provider.delete_event(creds, params.calendar_id, rid, timeout=params.timeout_seconds)
        except ConnectorError:
            raise

        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST,
            f"Unsupported Google Calendar operation '{operation}'.",
            retryable=False,
        )

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "output": {
                "connector_id": self.connector_id,
                "name": self.name,
                "status": self.status,
                "metadata": self._metadata,
            },
            "success": True,
        }

    async def op_describe(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": self.to_dict(), "success": True}

    @staticmethod
    def _require(value: Any, message: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, message, retryable=False)
        return text
