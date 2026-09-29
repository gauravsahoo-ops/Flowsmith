"""ServiceNow connector implementing the ConnectorSDK interface."""

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
from app.providers.servicenow import ServiceNowProviderClient


class ServiceNowConnectorParams(BaseModel):
    operation: str = Field(default="list_records")
    table: str = ""
    sys_id: str = ""
    query: str = ""
    fields: dict[str, Any] | None = None
    fields_csv: str = ""
    orderby: str = ""
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class ServiceNowConnector(ConnectorSDK):
    connector_id = "servicenow"
    display_name = "ServiceNow"
    description = "Manage ServiceNow ITSM records via the Table API."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = ServiceNowProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["servicenow"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("instance") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = ServiceNowConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid ServiceNow payload: {exc}", retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("servicenow") or {}
        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        table = str(raw.get("table") or params.table or "").strip()
        sys_id = str(raw.get("sys_id") or params.sys_id or "").strip()
        try:
            if op == "list_records":
                fields_csv = str(raw.get("fields_csv") or params.fields_csv or "")
                raw_fields = raw.get("fields")
                if isinstance(raw_fields, str):
                    fields_csv = fields_csv or raw_fields
                return await self._provider.list_records(
                    creds, table,
                    query=str(raw.get("query") or params.query or ""),
                    limit=int(raw.get("limit") or params.limit),
                    offset=int(raw.get("offset") or params.offset),
                    fields=fields_csv,
                    orderby=str(raw.get("orderby") or params.orderby or ""),
                    timeout=timeout)
            if op == "get_record":
                return await self._provider.get_record(creds, table, sys_id, timeout=timeout)
            if op == "create_record":
                fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else (params.fields or {})
                return await self._provider.create_record(creds, table, fields or {}, timeout=timeout)
            if op == "update_record":
                fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else (params.fields or {})
                return await self._provider.update_record(creds, table, sys_id, fields or {}, timeout=timeout)
            if op == "delete_record":
                return await self._provider.delete_record(creds, table, sys_id, timeout=timeout)
        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"ServiceNow {op} failed: {exc}", retryable=True) from exc
        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported ServiceNow operation '{operation}'.", retryable=False)

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        from app.connectors import ConnectorError

        try:
            return await self._provider.test_connection(creds)
        except ConnectorError as exc:
            return {"ok": False, "message": f"Connection failed ({exc.code})."}
        except Exception:
            return {"ok": False, "message": "Connection failed."}

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"connector_id": self.connector_id, "operations": ["list_records", "get_record", "create_record", "update_record", "delete_record"]}}
