"""Airtable connector implementing the ConnectorSDK interface.

Thin mapper over AirtableProviderClient; credentials arrive via
context["credentials"]["airtable"].
"""

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
from app.providers.airtable import AirtableProviderClient


class AirtableConnectorParams(BaseModel):
    operation: str = Field(default="list_records", description="list_records | get_record | create_record | update_record.")
    base_id: str = ""
    table_name: str = ""
    record_id: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)
    view: str = ""
    filter_by_formula: str = ""
    page_size: int = Field(default=100, ge=1, le=100)
    max_pages: int = Field(default=3, ge=1, le=10)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class AirtableConnector(ConnectorSDK):
    connector_id = "airtable"
    display_name = "Airtable"
    description = "Read and write records in Airtable bases."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = AirtableProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["airtable"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("personal_access_token") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = AirtableConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Airtable payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("airtable") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        base_id = str(raw.get("base_id") or params.base_id)
        table_name = str(raw.get("table_name") or params.table_name)

        try:
            if op == "list_records":
                return await self._provider.list_records(
                    creds, base_id, table_name,
                    view=str(raw.get("view") or params.view),
                    filter_by_formula=str(raw.get("filter_by_formula") or params.filter_by_formula),
                    page_size=params.page_size, max_pages=params.max_pages,
                    timeout=params.timeout_seconds,
                )
            if op == "get_record":
                return await self._provider.get_record(
                    creds, base_id, table_name,
                    str(raw.get("record_id") or params.record_id),
                    timeout=params.timeout_seconds,
                )
            if op == "create_record":
                fields_raw = raw.get("fields")
                fields = fields_raw if isinstance(fields_raw, dict) and fields_raw else params.fields
                return await self._provider.create_record(
                    creds, base_id, table_name, fields, timeout=params.timeout_seconds,
                )
            if op == "update_record":
                fields_raw = raw.get("fields")
                fields = fields_raw if isinstance(fields_raw, dict) and fields_raw else params.fields
                return await self._provider.update_record(
                    creds, base_id, table_name,
                    str(raw.get("record_id") or params.record_id),
                    fields, timeout=params.timeout_seconds,
                )
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported Airtable operation '{operation}'.", retryable=False,
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
