"""Workday connector implementing the ConnectorSDK interface."""

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
from app.providers.workday import WorkdayProviderClient


class WorkdayConnectorParams(BaseModel):
    operation: str = Field(default="query_wql")
    query: str = ""
    worker_id: str = ""
    org_id: str = ""
    search: str = ""
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    data: dict[str, Any] | None = None
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class WorkdayConnector(ConnectorSDK):
    connector_id = "workday"
    display_name = "Workday"
    description = "Manage HCM workers, organizations, and financial objects in Workday via WQL and REST."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = WorkdayProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["workday"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("host") or "").strip() and str(config.get("tenant") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = WorkdayConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Workday payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("workday") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        worker_id = str(raw.get("worker_id") or params.worker_id or "").strip()
        org_id = str(raw.get("org_id") or params.org_id or "").strip()

        try:
            if op == "query_wql":
                query_str = str(raw.get("query") or params.query or "")
                return await self._provider.query_wql(
                    creds, query_str,
                    limit=int(raw.get("limit") or params.limit),
                    offset=int(raw.get("offset") or params.offset),
                    timeout=timeout,
                )
            if op == "list_workers":
                return await self._provider.list_workers(
                    creds,
                    search=str(raw.get("search") or params.search or ""),
                    limit=int(raw.get("limit") or params.limit),
                    offset=int(raw.get("offset") or params.offset),
                    timeout=timeout,
                )
            if op == "get_worker":
                return await self._provider.get_worker(creds, worker_id, timeout=timeout)
            if op == "update_worker":
                data = raw.get("data") if isinstance(raw.get("data"), dict) else (params.data or {})
                return await self._provider.update_worker(creds, worker_id, data or {}, timeout=timeout)
            if op == "get_organization":
                return await self._provider.get_organization(creds, org_id, timeout=timeout)
            if op == "create_requisition":
                data = raw.get("data") if isinstance(raw.get("data"), dict) else (params.data or {})
                return await self._provider.create_requisition(creds, data or {}, timeout=timeout)
        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Workday {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Workday operation '{operation}'.", retryable=False)
