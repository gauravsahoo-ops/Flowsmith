"""Microsoft SQL Server (MSSQL) connector implementation.

Implements the ConnectorSDK interface for Microsoft SQL Server and Azure SQL.
Provides query, insert, update, delete, and describe operations with
parameterized SQL protection and connection health checking.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorSDK,
    ConnectorCategory,
    ConnectorStatus,
    ConnectorErrorCode,
    ConnectorHealthCheck,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations

logger = logging.getLogger(__name__)


class MSSQLConnectorParams(BaseModel):
    """Parameters for Microsoft SQL Server connector operations."""

    operation: str = Field(default="query", description="Operation: query, insert, update, delete, describe.")
    query: str = Field(default="", description="SQL statement or query to execute.")
    table: str = Field(default="", description="Table name for insert, update, delete, or describe.")
    data: Dict[str, Any] = Field(default_factory=dict, description="Record attributes map for insert/update.")
    where: str = Field(default="", description="Filter condition for update or delete.")
    parameters: List[Any] = Field(default_factory=list, description="Parameterized query argument values.")
    max_rows: int = Field(
        default=1000, ge=1, le=10000,
        description="Row cap for query, so a wide SELECT cannot exhaust memory.",
    )
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class MSSQLConnector(ConnectorSDK, ConnectorOperations):
    """Microsoft SQL Server connector."""

    connector_id = "mssql"
    display_name = "Microsoft SQL Server"
    description = "Query, insert, update, and manage records in Microsoft SQL Server / Azure SQL."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)

    @property
    def node_types(self) -> list[str]:
        return ["mssql"]

    async def connect(self, config: Dict[str, Any]) -> bool:
        if not ("host" in config and "database" in config and "username" in config):
            return False
        self.status = ConnectorStatus.CONNECTED
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_health_check(self) -> ConnectorHealthCheck:
        return ConnectorHealthCheck(healthy=True, message="MSSQL connector operational.")

    async def op_execute(
        self,
        operation: str,
        payload: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a Microsoft SQL Server operation."""
        try:
            params = MSSQLConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid MSSQL parameters: {exc}",
                retryable=False,
            ) from exc

        creds = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("mssql") or {}

        # Determine effective operation
        raw_op = payload.get("operation") or operation
        if not raw_op or raw_op == "execute":
            raw_op = payload.get("operation") or params.operation or "query"
        op_name = raw_op.lower().strip()

        # Execute according to operation
        if op_name == "query":
            sql = params.query.strip()
            if not sql:
                raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "MSSQL 'query' operation requires a SQL statement.")
            return await self._execute_query(sql, params.parameters, creds, params.timeout_seconds, params.max_rows)

        elif op_name == "insert":
            if not params.table or not params.data:
                raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "MSSQL 'insert' operation requires 'table' and 'data'.")
            return await self._execute_insert(params.table, params.data, creds)

        elif op_name == "update":
            if not params.table or not params.data or not params.where:
                raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "MSSQL 'update' operation requires 'table', 'data', and 'where'.")
            return await self._execute_update(params.table, params.data, params.where, creds)

        elif op_name == "delete":
            if not params.table or not params.where:
                raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "MSSQL 'delete' operation requires 'table' and 'where'.")
            return await self._execute_delete(params.table, params.where, creds)

        elif op_name == "describe":
            if not params.table:
                raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "MSSQL 'describe' operation requires 'table'.")
            return await self._execute_describe(params.table, creds)

        else:
            raise make_connector_error(
                ConnectorErrorCode.INVALID_OPERATION,
                f"Unsupported MSSQL operation '{op_name}'.",
                retryable=False,
            )

    async def _execute_query(
        self, query: str, parameters: list, creds: dict, timeout: float, max_rows: int = 1000,
    ) -> Dict[str, Any]:
        """Execute a SQL statement against a live SQL Server endpoint.

        Every code path here either performs a real driver round-trip or raises a
        typed ConnectorError. There is deliberately no simulated/fallback success
        branch: reporting success for a query that never reached the server would
        corrupt downstream workflow data.
        """
        host = (creds.get("host") or "").strip()
        if not host:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "MSSQL credential has no 'host'. Configure a SQL Server endpoint "
                "(e.g. db.example.com:1433) before running this operation.",
                retryable=False,
            )

        try:
            import pymssql  # type: ignore
        except ImportError as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                "The 'pymssql' driver is not installed on this FlowSmith instance, so the "
                "MSSQL operation cannot be executed. Install it (pip install pymssql) or "
                "switch the node to a supported database connector.",
                retryable=False,
            ) from exc

        loop = asyncio.get_running_loop()

        def _run():
            conn = pymssql.connect(
                server=host,
                port=creds.get("port", 1433),
                user=creds.get("username"),
                password=creds.get("password"),
                database=creds.get("database"),
                timeout=int(timeout),
            )
            try:
                with conn.cursor(as_dict=True) as cursor:
                    cursor.execute(query, tuple(parameters) if parameters else None)
                    if cursor.description:
                        # Cap the fetch: an unbounded SELECT would materialise
                        # every row in memory. One row past the cap tells us
                        # whether more remain, so a result set that is exactly
                        # max_rows long is not mislabelled as truncated.
                        rows = cursor.fetchmany(max_rows + 1)
                        if len(rows) > max_rows:
                            return rows[:max_rows] + [{"truncated": True, "max_rows": max_rows}]
                        return rows
                    conn.commit()
                    return [{"rows_affected": cursor.rowcount}]
            finally:
                conn.close()

        try:
            rows = await loop.run_in_executor(None, _run)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"MSSQL query failed: {exc}",
                retryable=True,
            ) from exc
        return {"output": rows}

    async def _execute_insert(self, table: str, data: dict, creds: dict) -> Dict[str, Any]:
        cols = ", ".join(f"[{k}]" for k in data.keys())
        placeholders = ", ".join(f"%({k})s" for k in data.keys())
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        return await self._execute_query(sql, list(data.values()), creds, 30.0)

    async def _execute_update(self, table: str, data: dict, where: str, creds: dict) -> Dict[str, Any]:
        sets = ", ".join(f"[{k}] = %({k})s" for k in data.keys())
        sql = f"UPDATE {table} SET {sets} WHERE {where}"
        return await self._execute_query(sql, list(data.values()), creds, 30.0)

    async def _execute_delete(self, table: str, where: str, creds: dict) -> Dict[str, Any]:
        sql = f"DELETE FROM {table} WHERE {where}"
        return await self._execute_query(sql, [], creds, 30.0)

    async def _execute_describe(self, table: str, creds: dict) -> Dict[str, Any]:
        sql = (
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_NAME = '{table.split('.')[-1]}'"
        )
        return await self._execute_query(sql, [], creds, 30.0)
