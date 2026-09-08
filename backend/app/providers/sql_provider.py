"""Shared SQL-database provider machinery (Phase 11 business connectors).

Powers the PostgreSQL and MySQL connectors. SQLAlchemy Core over a
credential-supplied DSN, executed off the event loop via
``asyncio.to_thread`` — the same pattern as the Database Query node.

Security:
- every connector enforces its own URL-scheme allowlist, so a Postgres
  credential can never be pointed at MySQL/SQLite/Oracle and vice versa;
- statements run through ``sqlalchemy.text()`` with bound parameters —
  callers pass values, never interpolated SQL.
"""

from __future__ import annotations

import re

import asyncio
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.connectors import ConnectorErrorCode, make_connector_error

# Messages that indicate a transient connection problem (retryable).
CONNECTION_LOSS_MARKERS: tuple[str, ...] = (
    "connection", "refused", "reset", "timeout", "timed out",
    "gone away", "server closed", "named pipe",
    "temporarily unavailable", "database is locked",
    "could not connect", "ssl connection", "terminating connection",
)

_MAX_ROWS = 1000


def _require_dsn(creds: dict[str, Any], credential_type: str) -> str:
    dsn = str((creds or {}).get("dsn") or "").strip()
    if not dsn:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            f"This operation needs a '{credential_type}' credential with a connection string (dsn).",
            retryable=False,
        )
    return dsn


def _validate_scheme(dsn: str, allowed_prefixes: tuple[str, ...], product: str) -> str:
    lowered = dsn.lower()
    if not any(lowered.startswith(prefix) for prefix in allowed_prefixes):
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            f"{product} credential DSN must start with one of: {', '.join(allowed_prefixes)}.",
            retryable=False,
        )
    return dsn


def _is_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True
    message = str(exc.orig if isinstance(exc, DBAPIError) and exc.orig is not None else exc).lower()
    return any(marker in message for marker in CONNECTION_LOSS_MARKERS)


def _run_query(engine: Engine, sql: str, params: dict[str, Any], max_rows: int) -> dict[str, Any]:
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        if result.returns_rows:
            rows = [dict(row._mapping) for row in result.fetchmany(max_rows)]
            return {"rows": rows, "count": len(rows), "truncated": len(rows) == max_rows}
        affected = result.rowcount or 0
        conn.commit()
        return {"affected_rows": affected}


def _run_execute(engine: Engine, sql: str, params: dict[str, Any]) -> dict[str, Any]:
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        affected = result.rowcount or 0
        conn.commit()
        return {"affected_rows": affected}


def _list_tables(engine: Engine) -> dict[str, Any]:
    inspector = inspect(engine)
    names = sorted(inspector.get_table_names())
    return {"tables": names, "count": len(names)}


def _insert_rows(
    engine: Engine, table: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    if not rows:
        raise ValueError("insert_rows needs at least one row.")
    keys = list(rows[0].keys())
    placeholders = ", ".join(f":{k}" for k in keys)
    columns = ", ".join(f'"{k}"' for k in keys)
    sql = text(f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})')  # noqa: S608 - identifiers quoted
    inserted = 0
    with engine.connect() as conn:
        for row in rows:
            missing = [k for k in keys if k not in row]
            if missing:
                raise ValueError(f"Row {inserted} is missing columns: {', '.join(missing)}")
            result = conn.execute(sql, {k: row[k] for k in keys})
            inserted += result.rowcount or 1
        conn.commit()
    return {"inserted": inserted}


class SQLProviderClient:
    """Base class for the SQL connectors; subclass pins the DSN policy."""

    credential_type: str = ""
    allowed_dsn_prefixes: tuple[str, ...] = ()
    product_name: str = ""

    def _engine(self, creds: dict[str, Any]) -> Engine:
        dsn = _validate_scheme(
            _require_dsn(creds, self.credential_type),
            self.allowed_dsn_prefixes,
            self.product_name,
        )
        try:
            return create_engine(dsn, pool_pre_ping=True, future=True)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                f"Invalid {self.product_name} connection string: {type(exc).__name__}.",
                retryable=False,
            ) from exc

    async def query(self, creds: dict[str, Any], sql: str, params: dict[str, Any] | None = None,
                    max_rows: int = _MAX_ROWS) -> dict[str, Any]:
        statement = str(sql or "").strip()
        if not statement:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=query requires sql.", retryable=False)
        client = self

        def job() -> dict[str, Any]:
            engine = client._engine(creds)
            try:
                return _run_query(engine, statement, params or {}, max_rows)
            except SQLAlchemyError as exc:
                raise make_connector_error(
                    ConnectorErrorCode.UNAVAILABLE if _is_connection_error(exc) else ConnectorErrorCode.BAD_REQUEST,
                    f"{client.product_name} query failed: {exc}",
                    retryable=_is_connection_error(exc),
                ) from exc
            finally:
                engine.dispose()

        return await asyncio.to_thread(job)

    async def execute(self, creds: dict[str, Any], sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        statement = str(sql or "").strip()
        if not statement:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=execute requires sql.", retryable=False)
        client = self

        def job() -> dict[str, Any]:
            engine = client._engine(creds)
            try:
                return _run_execute(engine, statement, params or {})
            except SQLAlchemyError as exc:
                raise make_connector_error(
                    ConnectorErrorCode.UNAVAILABLE if _is_connection_error(exc) else ConnectorErrorCode.BAD_REQUEST,
                    f"{client.product_name} execute failed: {exc}",
                    retryable=_is_connection_error(exc),
                ) from exc
            finally:
                engine.dispose()

        return await asyncio.to_thread(job)

    async def list_tables(self, creds: dict[str, Any]) -> dict[str, Any]:
        client = self

        def job() -> dict[str, Any]:
            engine = client._engine(creds)
            try:
                return _list_tables(engine)
            except SQLAlchemyError as exc:
                raise make_connector_error(
                    ConnectorErrorCode.UNAVAILABLE if _is_connection_error(exc) else ConnectorErrorCode.BAD_REQUEST,
                    f"{client.product_name} list_tables failed: {exc}",
                    retryable=_is_connection_error(exc),
                ) from exc
            finally:
                engine.dispose()

        return await asyncio.to_thread(job)

    async def insert_rows(self, creds: dict[str, Any], table: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        table_name = str(table or "").strip()
        if not table_name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=insert_rows requires a valid plain table name (alphanumeric/underscore only).", retryable=False)
        if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "operation=insert_rows requires rows: [{...}, ...].", retryable=False)
        client = self

        def job() -> dict[str, Any]:
            engine = client._engine(creds)
            try:
                return _insert_rows(engine, table_name, rows)
            except (SQLAlchemyError, ValueError) as exc:
                raise make_connector_error(
                    ConnectorErrorCode.UNAVAILABLE if _is_connection_error(exc) else ConnectorErrorCode.BAD_REQUEST,
                    f"{client.product_name} insert failed: {exc}",
                    retryable=_is_connection_error(exc),
                ) from exc
            finally:
                engine.dispose()

        return await asyncio.to_thread(job)
