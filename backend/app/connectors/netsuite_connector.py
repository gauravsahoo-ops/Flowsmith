"""Oracle NetSuite ERP connector implementing the ConnectorSDK interface."""

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
from app.providers.netsuite import NetSuiteProviderClient


class NetSuiteConnectorParams(BaseModel):
    operation: str = Field(default="query_suiteql")
    query: str = ""
    record_type: str = "customer"
    record_id: str = ""
    q: str = ""
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    data: dict[str, Any] | None = None
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class NetSuiteConnector(ConnectorSDK):
    connector_id = "netsuite"
    display_name = "Oracle NetSuite ERP"
    description = "Manage financial records, customers, and transactions via SuiteTalk REST Web Services."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = NetSuiteProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["netsuite"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("account_id") or config.get("realm") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = NetSuiteConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid NetSuite payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("netsuite") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        record_type = str(raw.get("record_type") or params.record_type or "customer").strip()
        record_id = str(raw.get("record_id") or params.record_id or "").strip()

        try:
            if op == "query_suiteql":
                query_str = str(raw.get("query") or params.query or "")
                return await self._provider.query_suiteql(
                    creds, query_str,
                    limit=int(raw.get("limit") or params.limit),
                    offset=int(raw.get("offset") or params.offset),
                    timeout=timeout,
                )
            if op == "list_records":
                return await self._provider.list_records(
                    creds, record_type,
                    q=str(raw.get("q") or params.q or ""),
                    limit=int(raw.get("limit") or params.limit),
                    offset=int(raw.get("offset") or params.offset),
                    timeout=timeout,
                )
            if op == "get_record":
                return await self._provider.get_record(creds, record_type, record_id, timeout=timeout)
            if op == "create_record":
                data = raw.get("data") if isinstance(raw.get("data"), dict) else (params.data or {})
                return await self._provider.create_record(creds, record_type, data or {}, timeout=timeout)
            if op == "update_record":
                data = raw.get("data") if isinstance(raw.get("data"), dict) else (params.data or {})
                return await self._provider.update_record(creds, record_type, record_id, data or {}, timeout=timeout)
            if op == "delete_record":
                return await self._provider.delete_record(creds, record_type, record_id, timeout=timeout)
            if op == "get_metadata":
                return await self._provider.get_metadata(creds, record_type, timeout=timeout)
        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"NetSuite {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported NetSuite operation '{operation}'.", retryable=False)
