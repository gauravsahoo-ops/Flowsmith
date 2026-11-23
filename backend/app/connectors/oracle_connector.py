"""Oracle Database connector implementation.

Real query/DDL/DML operations backed by the ``oracledb`` thin driver.
There is no simulated success path: every operation either performs a
database round-trip or raises a typed ConnectorError. Credentials arrive
through ``context["credentials"]["oracle"]`` (or ``connect()`` for direct use).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List

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

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]*$")


def _quote_identifier(name: str) -> str:
    """Quote an Oracle identifier, folding it to uppercase like unquoted SQL.

    Oracle stores unquoted identifiers in uppercase. Normalising here means a
    table created with ``CREATE TABLE customers`` is addressable as
    ``"CUSTOMERS"`` by insert/update/delete, instead of failing because a
    lowercase quoted name does not exist.
    """
    value = str(name or "").strip()
    if not _IDENTIFIER_RE.fullmatch(value):
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST,
            f"Invalid Oracle identifier: {name!r}",
            retryable=False,
        )
    return f'"{value.upper()}"'


def _quote_table(table: str) -> str:
    value = str(table or "").strip()
    parts = value.split(".")
    if not 1 <= len(parts) <= 2:
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST,
            f"Invalid Oracle table identifier: {table!r}",
            retryable=False,
        )
    return ".".join(_quote_identifier(part) for part in parts)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if hasattr(value, "read") and type(value).__name__ == "LOB":
        try:
            return value.read()
        except Exception:
            return str(value)
    return value


class OracleConnectorParams(BaseModel):
    """Parameters for Oracle Database connector operations."""

    operation: str = Field(default="query", description="Operation: query, execute, insert, update, delete, table_list.")
    query: str = Field(default="", description="SQL statement to execute.")
    table: str = Field(default="", description="Target table name.")
    data: Dict[str, Any] = Field(default_factory=dict, description="Record attributes map for insert/update.")
    where: str = Field(default="", description="Filter condition for update or delete.")
    parameters: List[Any] = Field(default_factory=list, description="Parameterized bind variables.")
    max_rows: int = Field(default=1000, ge=1, le=10000, description="Row cap for query.")
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class OracleConnector(ConnectorSDK, ConnectorOperations):
    """Oracle Database connector backed by a real oracledb connection."""

    connector_id = "oracle"
    display_name = "Oracle Database"
    description = "Query, insert, update, and manage records in Oracle Database instances."
    category = ConnectorCategory.API
    version = "1.1.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self.credentials: Dict[str, Any] = {}

    @property
    def node_types(self) -> list[str]:
        return ["oracle"]

    async def connect(self, config: Dict[str, Any]) -> bool:
        if not all(str((config or {}).get(k) or "").strip() for k in ("host", "username", "password")):
            return False
        self.credentials = dict(config or {})
        self.status = ConnectorStatus.CONNECTED
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED

    async def health_check(self) -> ConnectorHealthCheck:
        started = time.perf_counter()
        try:
            await asyncio.to_thread(self._query_sync, self.credentials or {}, "SELECT 1 FROM dual", [], 1, 5.0)
            return ConnectorHealthCheck(
                healthy=True,
                message="Oracle Database connection verified.",
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except Exception as exc:  # noqa: BLE001 - surface database failure
            return ConnectorHealthCheck(healthy=False, message=f"Oracle connection failed: {exc}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    async def op_execute(
        self,
        operation: str,
        payload: Dict[str, Any] | None = None,
        context: Dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        raw = payload or kwargs.get("params") or {}
        try:
            params = OracleConnectorParams.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid Oracle payload: {exc}",
                retryable=False,
            ) from exc

        creds = (
            ((context or {}).get("credentials") or {}).get("oracle")
            or self.credentials
            or {}
        )
        op = (raw.get("operation") if isinstance(raw, dict) else None) or operation or params.operation
        op_name = str(op).lower().strip()

        if op_name == "query":
            if not params.query.strip():
                raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Query parameter is required.", retryable=False)
            return await self._query(creds, params.query, params.parameters, params.max_rows, params.timeout_seconds)
        if op_name == "execute":
            if not params.query.strip():
                raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Query parameter is required.", retryable=False)
            return await self._execute(creds, params.query, params.parameters, params.timeout_seconds)
        if op_name == "insert":
            if not params.table or not params.data:
                raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Table and data are required for insert operation.", retryable=False)
            return await self._insert(creds, params.table, params.data, params.timeout_seconds)
        if op_name == "update":
            if not params.table or not params.data or not params.where:
                raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Table, data, and where are required for update operation.", retryable=False)
            return await self._update(creds, params.table, params.data, params.where, params.timeout_seconds)
        if op_name == "delete":
            if not params.table or not params.where:
                raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "Table and where are required for delete operation.", retryable=False)
            return await self._delete(creds, params.table, params.where, params.timeout_seconds)
        if op_name == "table_list":
            return await self._table_list(creds, params.timeout_seconds)
        raise make_connector_error(
            ConnectorErrorCode.INVALID_OPERATION,
            f"Unsupported Oracle operation '{op_name}'. Supported: query, execute, insert, update, delete, table_list.",
        )

    # Back-compat wrappers for callers of the previous handler names.
    async def op_query(self, params: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        parsed = OracleConnectorParams.model_validate(params)
        creds = ((context or {}).get("credentials") or {}).get("oracle") or self.credentials or {}
        return await self._query(creds, parsed.query, parsed.parameters, parsed.max_rows, parsed.timeout_seconds)

    async def op_query_execute(self, params: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        parsed = OracleConnectorParams.model_validate(params)
        creds = ((context or {}).get("credentials") or {}).get("oracle") or self.credentials or {}
        return await self._execute(creds, parsed.query, parsed.parameters, parsed.timeout_seconds)

    async def op_insert(self, params: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        parsed = OracleConnectorParams.model_validate(params)
        creds = ((context or {}).get("credentials") or {}).get("oracle") or self.credentials or {}
        return await self._insert(creds, parsed.table, parsed.data, parsed.timeout_seconds)

    async def op_update(self, payload: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        parsed = OracleConnectorParams.model_validate(payload)
        creds = ((context or {}).get("credentials") or {}).get("oracle") or self.credentials or {}
        return await self._update(creds, parsed.table, parsed.data, parsed.where, parsed.timeout_seconds)

    async def op_delete(self, payload: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        parsed = OracleConnectorParams.model_validate(payload)
        creds = ((context or {}).get("credentials") or {}).get("oracle") or self.credentials or {}
        return await self._delete(creds, parsed.table, parsed.where, parsed.timeout_seconds)

    async def op_table_list(self, params: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        parsed = OracleConnectorParams.model_validate(params)
        creds = ((context or {}).get("credentials") or {}).get("oracle") or self.credentials or {}
        return await self._table_list(creds, parsed.timeout_seconds)

    # ------------------------------------------------------------------
    # oracledb helpers (blocking work runs off the event loop)
    # ------------------------------------------------------------------

    @staticmethod
    def _require_oracledb():
        try:
            import oracledb  # noqa: PLC0415 - optional dependency
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Oracle support needs the 'oracledb' package (pip install oracledb).",
                retryable=False,
            ) from exc
        return oracledb

    @classmethod
    def _dsn(cls, creds: Dict[str, Any]) -> str:
        oracledb = cls._require_oracledb()
        host = str((creds or {}).get("host") or "").strip()
        if not host:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Oracle credential is missing 'host'.",
                retryable=False,
            )
        port = int((creds or {}).get("port") or 1521)
        service = str((creds or {}).get("service_name") or "").strip()
        sid = str((creds or {}).get("sid") or "").strip()
        if service:
            return oracledb.makedsn(host, port, service_name=service)
        if sid:
            return oracledb.makedsn(host, port, sid=sid)
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Oracle credential needs 'service_name' or 'sid'.",
            retryable=False,
        )

    @classmethod
    def _connect_sync(cls, creds: Dict[str, Any], timeout: float):
        oracledb = cls._require_oracledb()
        username = str((creds or {}).get("username") or "").strip()
        password = str((creds or {}).get("password") or "")
        if not username or not password:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Oracle credential is missing 'username' or 'password'.",
                retryable=False,
            )
        conn = oracledb.connect(
            user=username,
            password=password,
            dsn=cls._dsn(creds),
            tcp_connect_timeout=timeout,
        )
        conn.call_timeout = int(timeout * 1000)
        schema = str((creds or {}).get("schema_name") or "").strip()
        if schema:
            with conn.cursor() as cursor:
                cursor.execute(f"ALTER SESSION SET CURRENT_SCHEMA = {_quote_identifier(schema)}")
        return conn

    @staticmethod
    def _rows_from_cursor(cursor, max_rows: int) -> List[Dict[str, Any]]:
        columns = [col[0].lower() for col in (cursor.description or [])]
        rows = cursor.fetchmany(max_rows)
        return [{columns[i]: _json_safe(value) for i, value in enumerate(row)} for row in rows]

    def _query_sync(self, creds: Dict[str, Any], sql: str, binds: List[Any], max_rows: int, timeout: float) -> Dict[str, Any]:
        conn = self._connect_sync(creds, timeout)
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, binds or None)
                if cursor.description:
                    rows = self._rows_from_cursor(cursor, max_rows)
                    return {"rows": rows, "row_count": len(rows)}
                conn.commit()
                return {"rows": [], "row_count": 0, "affected_rows": cursor.rowcount or 0}
        finally:
            conn.close()

    def _execute_sync(self, creds: Dict[str, Any], sql: str, binds: List[Any], timeout: float) -> Dict[str, Any]:
        conn = self._connect_sync(creds, timeout)
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, binds or None)
                affected = cursor.rowcount or 0
                conn.commit()
                return {"status": "success", "affected_rows": affected}
        finally:
            conn.close()

    async def _query(self, creds, sql, binds, max_rows, timeout) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self._query_sync, creds, sql, binds, max_rows, timeout)
        except Exception as exc:
            raise self._translate(exc, "query") from exc

    async def _execute(self, creds, sql, binds, timeout) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self._execute_sync, creds, sql, binds, timeout)
        except Exception as exc:
            raise self._translate(exc, "execute") from exc

    async def _insert(self, creds, table, data, timeout) -> Dict[str, Any]:
        table_sql = _quote_table(table)
        columns = ", ".join(_quote_identifier(k) for k in data.keys())
        placeholders = ", ".join(f":{i + 1}" for i in range(len(data)))
        sql = f"INSERT INTO {table_sql} ({columns}) VALUES ({placeholders})"
        result = await self._execute(creds, sql, list(data.values()), timeout)
        return {**result, "table": table}

    async def _update(self, creds, table, data, where, timeout) -> Dict[str, Any]:
        table_sql = _quote_table(table)
        sets = ", ".join(f"{_quote_identifier(k)} = :{i + 1}" for i, k in enumerate(data))
        sql = f"UPDATE {table_sql} SET {sets} WHERE {where}"
        result = await self._execute(creds, sql, list(data.values()), timeout)
        return {**result, "table": table}

    async def _delete(self, creds, table, where, timeout) -> Dict[str, Any]:
        table_sql = _quote_table(table)
        result = await self._execute(creds, f"DELETE FROM {table_sql} WHERE {where}", [], timeout)
        return {**result, "table": table}

    async def _table_list(self, creds, timeout) -> Dict[str, Any]:
        result = await self._query(creds, "SELECT table_name FROM user_tables ORDER BY table_name", [], 10000, timeout)
        tables = [row.get("table_name") for row in result.get("rows", []) if row.get("table_name")]
        return {"tables": tables, "count": len(tables)}

    @staticmethod
    def _translate(exc: Exception, operation: str):
        from app.connectors import ConnectorError

        if isinstance(exc, ConnectorError):
            return exc
        return make_connector_error(
            ConnectorErrorCode.PROVIDER_ERROR,
            f"Oracle {operation} failed: {exc}",
            retryable=True,
        )
