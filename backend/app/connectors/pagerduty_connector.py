"""PagerDuty connector implementing the ConnectorSDK interface."""

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
from app.providers.pagerduty import PagerDutyProviderClient


class PagerDutyConnectorParams(BaseModel):
    operation: str = Field(default="list_incidents")
    incident_id: str = ""
    title: str = ""
    service_id: str = ""
    urgency: str = ""
    description: str = ""
    status: str = ""
    content: str = ""
    limit: int = Field(default=25, ge=1, le=100)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class PagerDutyConnector(ConnectorSDK):
    connector_id = "pagerduty"
    display_name = "PagerDuty"
    description = "Manage PagerDuty incidents and notes."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = PagerDutyProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["pagerduty"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("api_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = PagerDutyConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid PagerDuty payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("pagerduty") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        try:
            if op == "list_incidents":
                return await self._provider.list_incidents(
                    creds, int(raw.get("limit") or params.limit), timeout=timeout)
            if op == "get_incident":
                return await self._provider.get_incident(
                    creds, str(raw.get("incident_id") or params.incident_id), timeout=timeout)
            if op == "create_incident":
                return await self._provider.create_incident(
                    creds, str(raw.get("title") or params.title),
                    str(raw.get("service_id") or params.service_id),
                    str(raw.get("urgency") or params.urgency),
                    str(raw.get("description") or params.description), timeout=timeout)
            if op == "update_incident":
                fields = {k: str(raw.get(k) if raw.get(k) is not None else getattr(params, k))
                          for k in ("status", "urgency")}
                fields = {k: v for k, v in fields.items() if v}
                return await self._provider.update_incident(
                    creds, str(raw.get("incident_id") or params.incident_id), fields, timeout=timeout)
            if op == "resolve_incident":
                return await self._provider.resolve_incident(
                    creds, str(raw.get("incident_id") or params.incident_id), timeout=timeout)
            if op == "add_note":
                return await self._provider.add_note(
                    creds, str(raw.get("incident_id") or params.incident_id),
                    str(raw.get("content") or params.content), timeout=timeout)
        except ConnectorError:
            raise
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported PagerDuty operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Live credential probe (abilities); secret-safe failure messages."""
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_incidents", "get_incident", "create_incident", "update_incident", "resolve_incident", "add_note"]}}
