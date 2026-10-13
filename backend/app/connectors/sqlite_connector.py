"""SQLite connector implementation.

Implements the ConnectorSDK interface for SQLite databases.
Executes queries, DDL, and DML with in-memory or file-based databases using
Python's standard library sqlite3 with threadpool offloading.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
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


class SQLiteConnectorParams(BaseModel):
    """Parameters for SQLite connector operations."""

    operation: str = Field(default="query", description="Operation: query, insert, update, delete, execute.")
    query: str = Field(default="", description="SQL statement to execute.")
    table: str = Field(default="", description="Target table name.")
    data: Dict[str, Any] = Field(default_factory=dict, description="Record attributes map for insert/update.")
    where: str = Field(default="", description="Filter condition for update or delete.")
    parameters: List[Any] = Field(default_factory=list, description="Parameterized query values.")
    max_rows: int = Field(
        default=1000, ge=1, le=10000,
        description="Row cap for query/execute, so a wide SELECT cannot exhaust memory.",
    )
    database_path: str = Field(default=":memory:", description="Optional override database file path.")


class SQLiteConnector(ConnectorSDK, ConnectorOperations):
    """SQLite connector."""

    connector_id = "sqlite"
    display_name = "SQLite"
    description = "Query, insert, update, and manage SQLite databases."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._mem_conn: Optional[sqlite3.Connection] = None

    @property
    def node_types(self) -> list[str]:
        return ["sqlite"]

    async def connect(self, config: Dict[str, Any]) -> bool:
        self.status = ConnectorStatus.CONNECTED
        if config.get("database_path", ":memory:") == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        if self._mem_conn:
            self._mem_conn.close()
            self._mem_conn = None
        self._metadata.clear()

    async def op_health_check(self) -> ConnectorHealthCheck:
        return ConnectorHealthCheck(healthy=True, message="SQLite connector operational.")

    async def op_execute(
        self,
        operation: str,
        payload: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an SQLite operation."""
        try:
            params = SQLiteConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid SQLite parameters: {exc}",
                retryable=False,
            ) from exc

        creds = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("sqlite") or {}

        db_path = params.database_path or creds.get("database_path") or ":memory:"

        raw_op = payload.get("operation") or operation
        if not raw_op or raw_op == "execute":
            raw_op = payload.get("operation") or params.operation or "query"
        op_name = raw_op.lower().strip()

        loop = asyncio.get_running_loop()

        def _run_sqlite():
            if db_path == ":memory:":
                if not self._mem_conn:
                    self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
                    self._mem_conn.row_factory = sqlite3.Row
                conn = self._mem_conn
                should_close = False
            else:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                should_close = True

            cursor = conn.cursor()
            try:
                if op_name in ("query", "execute"):
                    sql = params.query.strip()
                    if not sql:
                        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "SQLite query cannot be empty.")
                    cursor.execute(sql, tuple(params.parameters) if params.parameters else ())
                    if cursor.description:
                        # Cap the fetch: an unbounded SELECT would materialise
                        # every row in memory. One row past the cap tells us
                        # whether more remain, so a result set that is exactly
                        # max_rows long is not mislabelled as truncated.
                        rows = [dict(row) for row in cursor.fetchmany(params.max_rows + 1)]
                        if len(rows) > params.max_rows:
                            return [
                                *rows[:params.max_rows],
                                {"truncated": True, "max_rows": params.max_rows},
                            ]
                        return rows
                    conn.commit()
                    return [{"rows_affected": cursor.rowcount}]

                elif op_name == "insert":
                    if not params.table or not params.data:
                        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "SQLite insert requires 'table' and 'data'.")
                    cols = ", ".join(params.data.keys())
                    placeholders = ", ".join("?" for _ in params.data)
                    sql = f"INSERT INTO {params.table} ({cols}) VALUES ({placeholders})"
                    cursor.execute(sql, tuple(params.data.values()))
                    conn.commit()
                    return [{"id": cursor.lastrowid, "rows_affected": cursor.rowcount, "status": "inserted"}]

                elif op_name == "update":
                    if not params.table or not params.data or not params.where:
                        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "SQLite update requires 'table', 'data', and 'where'.")
                    set_clause = ", ".join(f"{k} = ?" for k in params.data.keys())
                    sql = f"UPDATE {params.table} SET {set_clause} WHERE {params.where}"
                    cursor.execute(sql, tuple(params.data.values()))
                    conn.commit()
                    return [{"rows_affected": cursor.rowcount, "status": "updated"}]

                elif op_name == "delete":
                    if not params.table or not params.where:
                        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "SQLite delete requires 'table' and 'where'.")
                    sql = f"DELETE FROM {params.table} WHERE {params.where}"
                    cursor.execute(sql)
                    conn.commit()
                    return [{"rows_affected": cursor.rowcount, "status": "deleted"}]

                else:
                    raise make_connector_error(
                        ConnectorErrorCode.INVALID_OPERATION,
                        f"Unsupported SQLite operation '{op_name}'.",
                    )
            finally:
                if should_close:
                    conn.close()

        try:
            results = await loop.run_in_executor(None, _run_sqlite)
            return {"output": results}
        except Exception as exc:
            if isinstance(exc, Exception) and hasattr(exc, "code"):
                raise
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"SQLite error: {exc}",
                retryable=False,
            ) from exc
