"""Database Query node (spec 7, node #7).

Runs SQL against a database whose connection string comes from a
"database" credential (e.g. `sqlite:///app.db` or
`postgresql+psycopg://user:pass@host/db`).

- SELECT-like statements produce one output item per row.
- INSERT/UPDATE/DELETE produce `{"affected_rows": n}`.

SQLAlchemy core with `text()`; no ORM involved inside the node.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.engine.errors import NodeExecutionError
from app.engine.node_base import CONDITIONALLY_IDEMPOTENT, BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class DatabaseQueryParams(BaseModel):
    sql: str = Field(min_length=1, description="SQL statement to run.")
    params: dict[str, Any] = Field(default_factory=dict, description="Bound parameters (optional).")


@register
class DatabaseQueryNode(BaseNode[DatabaseQueryParams]):
    node_type = "database_query"
    display_name = "Database Query"
    version = 1
    description = "Runs SQL and returns the result rows."
    category = "Database"
    icon = "🗄️"
    parameters_schema = DatabaseQueryParams
    credential_types = ["database"]
    # SELECT runs are pure; INSERT/UPDATE/DELETE are not.
    idempotency = CONDITIONALLY_IDEMPOTENT

    _CONNECTION_LOSS_MARKERS = (
        "unable to open",
        "connection", "refused", "reset", "timeout",
        "gone away", "server closed", "named pipe",
        "temporarily unavailable", "database is locked",
    )

    async def run(
        self,
        ctx: NodeContext,
        params: DatabaseQueryParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        creds = ctx.credentials.get("database")
        if not creds or not creds.get("dsn"):
            raise NodeExecutionError(
                "This node needs a database credential with a connection string (dsn).",
                code="CREDENTIALS_REQUIRED", node_id="database_query", retryable=False,
            )

        engine = create_engine(creds["dsn"], pool_pre_ping=True, future=True)
        try:
            return await asyncio.to_thread(_query, engine, params)
        except SQLAlchemyError as exc:
            retryable = _is_connection_error(exc, self._CONNECTION_LOSS_MARKERS)
            raise NodeExecutionError(
                f"Database query failed: {exc}",
                code="DB_CONNECTION_ERROR" if retryable else "SQL_ERROR",
                node_id="database_query",
                retryable=retryable,
            ) from exc
        finally:
            engine.dispose()


def _is_connection_error(exc: SQLAlchemyError, markers: tuple[str, ...]) -> bool:
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True
    if isinstance(exc, DBAPIError):
        message = str(exc.orig if exc.orig is not None else exc).lower()
    else:
        message = str(exc).lower()
    return any(marker in message for marker in markers)


def _query(engine: Engine, params: DatabaseQueryParams) -> NodeResult:
    with engine.connect() as conn:
        result = conn.execute(text(params.sql), params.params)
        if result.returns_rows:
            rows = [dict(row._mapping) for row in result]
            return NodeResult(output_items=rows if rows else [{"rowCount": 0, "rows": []}])
        affected = result.rowcount or 0
        return NodeResult(output_items=[{"success": True, "affected_rows": affected}])