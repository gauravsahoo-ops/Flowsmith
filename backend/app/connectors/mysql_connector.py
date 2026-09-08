"""MySQL connector implementing the ConnectorSDK interface.

Thin operation mapper over MySQLProviderClient — credentials arrive via
context["credentials"]["mysql"].
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
from app.providers.mysql import MySQLProviderClient


class MySQLConnectorParams(BaseModel):
    operation: str = Field(default="query", description="query | execute | insert_rows | list_tables.")
    sql: str = Field(default="", description="SQL statement (query/execute).")
    params: dict[str, Any] = Field(default_factory=dict, description="Bound parameters.")
    table: str = Field(default="", description="Target table (insert_rows).")
    rows: list[dict[str, Any]] = Field(default_factory=list, description="Rows to insert (insert_rows).")
    max_rows: int = Field(default=1000, ge=1, le=10000, description="Row cap for query.")


class MySQLConnector(ConnectorSDK):
    connector_id = "mysql"
    display_name = "MySQL"
    description = "Run parameterised SQL against MySQL / MariaDB databases."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = MySQLProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["mysql"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("dsn") or "").strip())

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
            params = MySQLConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid MySQL payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("mysql") or {}

        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()

        try:
            if op == "query":
                return await self._provider.query(
                    creds, params.sql, params.params or None, max_rows=params.max_rows,
                )
            if op == "execute":
                return await self._provider.execute(creds, params.sql, params.params or None)
            if op == "insert_rows":
                rows = (payload.get("rows") if isinstance(payload, dict) else None) or params.rows
                return await self._provider.insert_rows(
                    creds, str(payload.get("table") or params.table), rows,
                )
            if op == "list_tables":
                return await self._provider.list_tables(creds)
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported MySQL operation '{operation}'.", retryable=False,
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
