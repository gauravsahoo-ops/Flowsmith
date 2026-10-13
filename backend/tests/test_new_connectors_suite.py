"""Comprehensive test suite for expanded FlowSmith connectors and nodes.

Validates MSSQL, SQLite, RabbitMQ, Compression, and the ParameterSchemaBuilder.
"""

import pytest
from app.connectors.mssql_connector import MSSQLConnector
from app.connectors.sqlite_connector import SQLiteConnector
from app.connectors.rabbitmq_connector import RabbitMQConnector
from app.nodes.compression import CompressionNode, CompressionParams
from app.parameters import ParameterSchemaBuilder


@pytest.mark.asyncio
async def test_sqlite_connector_full_lifecycle():
    """Test full SQLite lifecycle: create table, insert, query, update, delete."""
    connector = SQLiteConnector()
    assert await connector.connect({}) is True

    # 1. Create table via execute
    ddl = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);"
    res = await connector.op_execute("execute", {"query": ddl, "database_path": ":memory:"})
    assert "output" in res

    # 2. Insert rows
    ins1 = await connector.op_execute(
        "insert",
        {"table": "users", "data": {"name": "Alice", "email": "alice@example.com"}, "database_path": ":memory:"},
    )
    assert ins1["output"][0]["status"] == "inserted"

    # 3. Query
    query_res = await connector.op_execute(
        "query",
        {"query": "SELECT * FROM users", "database_path": ":memory:"},
    )
    assert "output" in query_res

    # 4. Update
    upd_res = await connector.op_execute(
        "update",
        {"table": "users", "data": {"name": "Alice Cooper"}, "where": "id = 1", "database_path": ":memory:"},
    )
    assert upd_res["output"][0]["status"] == "updated"

    # 5. Delete
    del_res = await connector.op_execute(
        "delete",
        {"table": "users", "where": "id = 1", "database_path": ":memory:"},
    )
    assert del_res["output"][0]["status"] == "deleted"

    await connector.disconnect()


@pytest.mark.asyncio
async def test_sqlite_query_is_capped_at_max_rows():
    """A wide SELECT must not materialise every row into memory.

    The fetch is bounded by max_rows; the cap is reported as a trailing
    ``truncated`` item so downstream steps can tell they are not seeing
    the whole result set.
    """
    connector = SQLiteConnector()
    assert await connector.connect({}) is True

    await connector.op_execute("execute", {"query": "CREATE TABLE nums (n INTEGER)"})
    await connector.op_execute(
        "execute",
        {"query": "INSERT INTO nums (n) VALUES " + ",".join(f"({i})" for i in range(25))},
    )

    res = await connector.op_execute("query", {"query": "SELECT n FROM nums ORDER BY n", "max_rows": 10})

    rows = [r for r in res["output"] if "truncated" not in r]
    assert len(rows) == 10
    # The cap keeps the first N rows in order, not an arbitrary subset.
    assert [r["n"] for r in rows] == list(range(10))
    # Truncation is reported rather than silently dropping the tail.
    assert res["output"][-1] == {"truncated": True, "max_rows": 10}

    await connector.disconnect()


@pytest.mark.asyncio
async def test_sqlite_exact_row_count_is_not_reported_as_truncated():
    """A result set exactly max_rows long is full, not truncated."""
    connector = SQLiteConnector()
    assert await connector.connect({}) is True

    await connector.op_execute("execute", {"query": "CREATE TABLE nums (n INTEGER)"})
    await connector.op_execute(
        "execute",
        {"query": "INSERT INTO nums (n) VALUES " + ",".join(f"({i})" for i in range(10))},
    )

    res = await connector.op_execute("query", {"query": "SELECT n FROM nums", "max_rows": 10})

    # fetchmany(max_rows + 1) distinguishes "exactly full" from "capped".
    assert len(res["output"]) == 10
    assert not any("truncated" in r for r in res["output"])

    await connector.disconnect()


@pytest.mark.asyncio
async def test_mssql_connector_reports_errors_instead_of_faking_success():
    """MSSQL must never report success for a query that never reached a server.

    Previously a missing driver or a mock/localhost host returned a fabricated
    ``{"executed": True, "rows_affected": 1, "status": "success"}``. Every path
    now either performs a real driver round-trip or raises a typed error.
    """
    from app.connectors import ConnectorError, ConnectorErrorCode

    connector = MSSQLConnector()
    assert await connector.connect({"host": "db.example.com", "database": "test", "username": "sa"}) is True

    # No host configured -> typed NOT_CONFIGURED (no invented rows)
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute("query", {"query": "SELECT 1"}, context={"credentials": {"mssql": {}}})
    assert exc_info.value.code == ConnectorErrorCode.NOT_CONFIGURED.value

    # Missing pymssql driver -> typed UNAVAILABLE with an actionable message.
    # (pymssql is not installed in this environment; if it ever is, the driver
    #  will genuinely attempt a connection and fail with PROVIDER_ERROR —
    #  either way, never a fabricated success.)
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "query",
            {"query": "SELECT TOP 10 * FROM Customers", "parameters": []},
            context={"credentials": {"mssql": {"host": "db.example.com"}}},
        )
    assert exc_info.value.code in (
        ConnectorErrorCode.UNAVAILABLE.value,
        ConnectorErrorCode.PROVIDER_ERROR.value,
    )
    # The fabricated fields from the old fallback must be absent
    assert "rows_affected" not in str(exc_info.value)
    assert "executed via mssql abstraction" not in str(exc_info.value).lower()

    # Parameter validation still rejects malformed requests
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute("update", {"table": "T", "data": {"a": 1}})
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value

    await connector.disconnect()


@pytest.mark.asyncio
async def test_rabbitmq_connector_reports_errors_instead_of_faking_success():
    """RabbitMQ must never report 'published' for a message that was not sent."""
    import importlib.util

    from app.connectors import ConnectorError, ConnectorErrorCode

    connector = RabbitMQConnector()
    assert await connector.connect({"host": "mq.example.com", "username": "guest"}) is True

    # No host -> typed NOT_CONFIGURED
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute("publish", {"routing_key": "x", "payload": {}}, context={"credentials": {"rabbitmq": {}}})
    assert exc_info.value.code == ConnectorErrorCode.NOT_CONFIGURED.value

    # Unknown operation -> typed INVALID_OPERATION
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "teleport",
            {"routing_key": "x"},
            context={"credentials": {"rabbitmq": {"host": "mq.example.com"}}},
        )
    assert exc_info.value.code == ConnectorErrorCode.INVALID_OPERATION.value

    if importlib.util.find_spec("aio_pika") is None:
        # Driver absent -> typed UNAVAILABLE, explicitly NOT a success.
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(
                "publish",
                {"exchange": "amq.direct", "routing_key": "orders", "payload": {"order_id": 999}},
                context={"credentials": {"rabbitmq": {"host": "mq.example.com"}}},
            )
        assert exc_info.value.code == ConnectorErrorCode.UNAVAILABLE.value
        assert "success" not in str(exc_info.value).lower()

    await connector.disconnect()


@pytest.mark.asyncio
async def test_schedule_and_webhook_connectors_are_labelled_config_not_success():
    """Trigger connectors perform no outbound call and must say so."""
    from app.connectors.schedule_connector import ScheduleConnector
    from app.connectors.webhook_connector import WebhookConnector

    sched = await ScheduleConnector().op_execute("execute", {"cron": "0 9 * * 1-5", "timezone": "UTC"})
    assert sched["kind"] == "trigger_config"
    assert sched["performed_outbound_call"] is False
    # next_fire is genuinely computed, not asserted
    assert sched["output"]["next_fire"] is not None
    assert "T" in sched["output"]["next_fire"]

    hook = await WebhookConnector().op_execute("execute", {"path": "orders", "method": "POST"})
    assert hook["kind"] == "trigger_config"
    assert hook["performed_outbound_call"] is False
    assert hook["output"]["path"] == "orders"


@pytest.mark.asyncio
async def test_compression_node():
    """Test CompressionNode zip, unzip, gzip, and gunzip operations."""
    node = CompressionNode()

    # 1. Zip compression
    items_to_zip = [
        {"filename": "doc1.txt", "content": "Hello World from document 1"},
        {"filename": "doc2.txt", "content": "Second document content"},
    ]
    zip_params = CompressionParams(operation="zip", archive_name="docs.zip", source_field="content")
    zip_result = await node.run(None, zip_params, items_to_zip)
    assert len(zip_result.output_items) == 1
    archive_item = zip_result.output_items[0]
    assert archive_item["filename"] == "docs.zip"
    assert "base64" in archive_item

    # 2. Unzip extraction
    unzip_params = CompressionParams(operation="unzip", source_field="base64")
    unzip_result = await node.run(None, unzip_params, [archive_item])
    assert len(unzip_result.output_items) == 2
    assert unzip_result.output_items[0]["filename"] == "doc1.txt"
    assert unzip_result.output_items[0]["content"] == "Hello World from document 1"

    # 3. Gzip compression
    gzip_params = CompressionParams(operation="gzip", file_name="payload.json", source_field="text")
    gzip_result = await node.run(None, gzip_params, [{"text": "Sample text to be compressed with gzip"}])
    assert len(gzip_result.output_items) == 1
    gz_item = gzip_result.output_items[0]
    assert gz_item["filename"] == "payload.json.gz"
    assert "base64" in gz_item

    # 4. Gunzip decompression
    gunzip_params = CompressionParams(operation="gunzip", source_field="base64")
    gunzip_result = await node.run(None, gunzip_params, [gz_item])
    assert len(gunzip_result.output_items) == 1
    assert gunzip_result.output_items[0]["text"] == "Sample text to be compressed with gzip"


def test_parameter_schema_builder():
    """Test ParameterSchemaBuilder extracting fields and conditional rules."""
    raw_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["query", "create", "delete"], "default": "query"},
            "soql": {"type": "string", "title": "SOQL Query", "default": "SELECT Id FROM Account"},
            "record": {"type": "object", "title": "Record Data"},
            "record_id": {"type": "string", "title": "Record ID"},
            "timeout_seconds": {"type": "number", "default": 30},
        },
        "required": ["operation"],
    }
    operations_meta = {
        "query": {"properties": ["soql"]},
        "create": {"properties": ["record"]},
        "delete": {"properties": ["record_id"]},
    }

    fields = ParameterSchemaBuilder.extract_from_json_schema(raw_schema, operations_meta)
    assert len(fields) == 5

    # Check soql field conditional visibility
    soql_field = next(f for f in fields if f.name == "soql")
    assert soql_field.show_if == {"operation": ["query"]}
    assert soql_field.group == "parameters"

    # Check timeout is grouped as advanced
    timeout_field = next(f for f in fields if f.name == "timeout_seconds")
    assert timeout_field.advanced is True
    assert timeout_field.group == "advanced"
