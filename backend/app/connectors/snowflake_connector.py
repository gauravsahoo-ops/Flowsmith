"""Snowflake Data Cloud connector implementing the ConnectorSDK interface."""

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
from app.providers.snowflake import SnowflakeProviderClient


class SnowflakeConnectorParams(BaseModel):
    operation: str = Field(default="execute_query")
    statement: str = ""
    statement_handle: str = ""
    table_name: str = ""
    warehouse: str = ""
    database: str = ""
    schema_name: str = ""
    role: str = ""
    partition: int = 0
    wait_for_completion: bool = True
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class SnowflakeConnector(ConnectorSDK):
    connector_id = "snowflake"
    display_name = "Snowflake Data Cloud"
    description = "Query and manage Snowflake data warehouses and schemas via the SQL REST API v2."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = SnowflakeProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["snowflake"]

    async def connect(self, config: dict[str, Any]) -> bool:
        account = str(config.get("account") or "").strip()
        token = str(config.get("token") or config.get("api_key") or "").strip()
        return bool(account and token)

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = SnowflakeConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Snowflake payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("snowflake") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        warehouse = str(raw.get("warehouse") or params.warehouse or "").strip() or None
        database = str(raw.get("database") or params.database or "").strip() or None
        schema = str(raw.get("schema") or raw.get("schema_name") or params.schema_name or "").strip() or None
        role = str(raw.get("role") or params.role or "").strip() or None

        try:
            if op == "execute_query":
                statement = str(raw.get("statement") or params.statement or "").strip()
                if not statement:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "SQL statement is required.", retryable=False)
                wait = raw.get("wait_for_completion", params.wait_for_completion)
                return await self._provider.execute_statement(
                    creds,
                    statement,
                    warehouse=warehouse,
                    database=database,
                    schema=schema,
                    role=role,
                    timeout=timeout,
                    wait_for_completion=bool(wait),
                )

            if op == "get_query_results":
                handle = str(raw.get("statement_handle") or params.statement_handle or "").strip()
                if not handle:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "statement_handle is required.", retryable=False)
                partition = int(raw.get("partition", params.partition))
                return await self._provider.get_statement(creds, handle, partition=partition, timeout=timeout)

            if op == "cancel_query":
                handle = str(raw.get("statement_handle") or params.statement_handle or "").strip()
                if not handle:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "statement_handle is required.", retryable=False)
                return await self._provider.cancel_statement(creds, handle, timeout=timeout)

            if op == "describe_table":
                table_name = str(raw.get("table_name") or params.table_name or "").strip()
                if not table_name:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "table_name is required for describe_table.", retryable=False)
                return await self._provider.describe_table(creds, table_name, database=database, schema=schema, timeout=timeout)

            if op == "list_tables":
                return await self._provider.list_tables(creds, database=database, schema=schema, timeout=timeout)

        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Snowflake {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Snowflake operation '{operation}'.", retryable=False)
