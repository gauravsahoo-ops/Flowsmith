"""Database Query node tests (spec 51.3), backed by a real SQLite file."""

from __future__ import annotations

import logging
import sqlite3

import httpx
import pytest
from pydantic import ValidationError

from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.database_query import DatabaseQueryNode, DatabaseQueryParams


@pytest.fixture
def dsn(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO users (name) VALUES (?)", [("Alice",), ("Bob",), ("Carol",)])
    conn.commit()
    conn.close()
    return f"sqlite:///{db}"


async def _run(params: dict, items: list[dict], dsn: str):
    node = DatabaseQueryNode()
    p = DatabaseQueryParams.model_validate(params)
    ctx = NodeContext(
        execution_id="exec_1", workflow_id="wf_1",
        logger=logging.getLogger("test"), http_client=httpx.AsyncClient(),
        credentials={"database": {"dsn": dsn}},
    )
    return await node.run(ctx, p, items)


# --- valid input -----------------------------------------------------------

async def test_select_returns_one_item_per_row(dsn):
    result = await _run({"sql": "SELECT id, name FROM users ORDER BY id"}, [], dsn)
    assert result.output_items == [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
        {"id": 3, "name": "Carol"},
    ]


async def test_insert_returns_affected_rows(dsn):
    result = await _run({"sql": "INSERT INTO users (name) VALUES ('Dana')"}, [], dsn)
    assert result.output_items == [{"success": True, "affected_rows": 1}]


async def test_update_returns_affected_rows(dsn):
    result = await _run({"sql": "UPDATE users SET name = 'A' WHERE id = 1"}, [], dsn)
    assert result.output_items == [{"success": True, "affected_rows": 1}]


async def test_bound_params(dsn):
    result = await _run(
        {"sql": "SELECT name FROM users WHERE id = :id", "params": {"id": 2}}, [], dsn,
    )
    assert result.output_items == [{"name": "Bob"}]


async def test_select_no_rows_returns_empty_item(dsn):
    result = await _run({"sql": "SELECT name FROM users WHERE id = 999"}, [], dsn)
    assert result.output_items == [{"rowCount": 0, "rows": []}]


# --- external failure --------------------------------------------------------

async def test_bad_sql_raises_permanent_error(dsn):
    with pytest.raises(NodeExecutionError) as exc:
        await _run({"sql": "SELECT * FROM missing_table"}, [], dsn)
    assert exc.value.code == "SQL_ERROR"
    assert exc.value.retryable is False


async def test_connection_failure_is_retryable():
    with pytest.raises(NodeExecutionError) as exc:
        await _run(
            {"sql": "SELECT 1"},
            [],
            "sqlite:///Z:/definitely/missing/path/db.sqlite",
        )
    assert exc.value.code == "DB_CONNECTION_ERROR"
    assert exc.value.retryable is True


# --- credential failure --------------------------------------------------------

async def test_missing_credential_raises_permanent_error():
    node = DatabaseQueryNode()
    params = DatabaseQueryParams.model_validate({"sql": "SELECT 1"})
    ctx = NodeContext(
        execution_id="exec_1", workflow_id="wf_1",
        logger=logging.getLogger("test"), http_client=httpx.AsyncClient(),
        credentials={},
    )
    with pytest.raises(NodeExecutionError) as exc:
        await node.run(ctx, params, [{}])
    assert exc.value.code == "CREDENTIALS_REQUIRED"
    assert exc.value.retryable is False


# --- invalid input ------------------------------------------------------------

async def test_empty_sql_rejected():
    with pytest.raises(ValidationError):
        DatabaseQueryParams.model_validate({"sql": ""})


# --- row cap ------------------------------------------------------------------

async def test_query_is_capped_at_max_rows(tmp_path):
    db = tmp_path / "big.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (n INTEGER)")
    conn.executemany("INSERT INTO t (n) VALUES (?)", [(i,) for i in range(50)])
    conn.commit()
    conn.close()
    dsn = f"sqlite:///{db}"

    result = await _run({"sql": "SELECT n FROM t ORDER BY n", "max_rows": 10}, [], dsn)

    assert len(result.output_items) == 10
    assert result.metadata["truncated"] is True
    assert result.metadata["row_count"] == 10
    assert result.metadata["max_rows"] == 10
    # The cap takes the first N rows, in order, rather than an arbitrary subset.
    assert [row["n"] for row in result.output_items] == list(range(10))


async def test_exact_row_count_is_not_reported_as_truncated(tmp_path):
    db = tmp_path / "exact.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (n INTEGER)")
    conn.executemany("INSERT INTO t (n) VALUES (?)", [(i,) for i in range(10)])
    conn.commit()
    conn.close()
    dsn = f"sqlite:///{db}"

    result = await _run({"sql": "SELECT n FROM t", "max_rows": 10}, [], dsn)

    # fetchmany(max_rows + 1) distinguishes "exactly full" from "capped".
    assert len(result.output_items) == 10
    assert result.metadata["truncated"] is False


async def test_uncapped_result_reports_truncation_flag(dsn):
    result = await _run({"sql": "SELECT id, name FROM users ORDER BY id"}, [], dsn)
    assert result.metadata["truncated"] is False
    assert result.metadata["row_count"] == 3


async def test_max_rows_bounds_are_validated():
    with pytest.raises(ValidationError):
        DatabaseQueryParams.model_validate({"sql": "SELECT 1", "max_rows": 0})
    with pytest.raises(ValidationError):
        DatabaseQueryParams.model_validate({"sql": "SELECT 1", "max_rows": 100000})
