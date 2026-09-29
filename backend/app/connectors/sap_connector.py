"""SAP S/4HANA ERP connector implementing the ConnectorSDK interface."""

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
from app.providers.sap_s4hana import SapS4HanaProviderClient


class SapConnectorParams(BaseModel):
    operation: str = Field(default="query_odata")
    service: str = "API_BUSINESS_PARTNER"
    entity_set: str = "A_BusinessPartner"
    entity_key: str = ""
    filter: str = ""
    select: str = ""
    top: int = Field(default=50, ge=1, le=1000)
    skip: int = Field(default=0, ge=0)
    orderby: str = ""
    expand: str = ""
    data: dict[str, Any] | None = None
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class SapConnector(ConnectorSDK):
    connector_id = "sap"
    display_name = "SAP S/4HANA"
    description = "Manage business entities, sales orders, and partners via SAP S/4HANA OData services."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = SapS4HanaProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["sap"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("base_url") or config.get("host") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = SapConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid SAP payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("sap") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds
        service = str(raw.get("service") or params.service or "API_BUSINESS_PARTNER").strip()
        entity_set = str(raw.get("entity_set") or params.entity_set or "").strip()
        entity_key = str(raw.get("entity_key") or params.entity_key or "").strip()

        try:
            if op == "query_odata":
                return await self._provider.query_odata(
                    creds, service, entity_set,
                    filter_expr=str(raw.get("filter") or params.filter or ""),
                    select_fields=str(raw.get("select") or params.select or ""),
                    top=int(raw.get("top") or params.top),
                    skip=int(raw.get("skip") or params.skip),
                    orderby=str(raw.get("orderby") or params.orderby or ""),
                    expand=str(raw.get("expand") or params.expand or ""),
                    timeout=timeout,
                )
            if op == "get_entity":
                return await self._provider.get_entity(
                    creds, service, entity_set, entity_key,
                    select_fields=str(raw.get("select") or params.select or ""),
                    timeout=timeout,
                )
            if op == "create_entity":
                data = raw.get("data") if isinstance(raw.get("data"), dict) else (params.data or {})
                return await self._provider.create_entity(creds, service, entity_set, data or {}, timeout=timeout)
            if op == "update_entity":
                data = raw.get("data") if isinstance(raw.get("data"), dict) else (params.data or {})
                return await self._provider.update_entity(creds, service, entity_set, entity_key, data or {}, timeout=timeout)
            if op == "delete_entity":
                return await self._provider.delete_entity(creds, service, entity_set, entity_key, timeout=timeout)
            if op == "get_metadata":
                return await self._provider.get_metadata(creds, service, timeout=timeout)
        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"SAP {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported SAP operation '{operation}'.", retryable=False)
