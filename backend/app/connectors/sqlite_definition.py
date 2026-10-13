"""SQLite Database connector definition.

Clean-room versioned ConnectorDefinitionV1 for SQLite.
Supports file-based and in-memory database queries, inserts, updates, deletes, and DDL execution.
"""

from __future__ import annotations

from typing import Any, Dict
from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

SQLITE_CONNECTOR_KEY = "sqlite"
SQLITE_CONNECTOR_VERSION = "1.0.0"
SQLITE_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str,
    display_name: str,
    description: str,
    input_properties: Dict[str, Any],
    required: list[str],
    *,
    output_schema: Dict[str, Any],
    retryable: bool = False,
    idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=SQLITE_CONNECTOR_KEY,
        connector_version=SQLITE_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=SQLITE_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="sqlite",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["sqlite"],
    )


def _sqlite_operations() -> Dict[str, ConnectorOperationV1]:
    query_prop = {
        "type": "string",
        "title": "SQL Query",
        "default": "SELECT * FROM sqlite_master WHERE type='table'",
        "description": "SQL query or statement to execute.",
    }
    table_prop = {
        "type": "string",
        "title": "Table Name",
        "default": "",
        "description": "Target table name.",
    }
    data_prop = {
        "type": "object",
        "title": "Data / Row",
        "default": {},
        "description": "Column and value map for insert or update.",
    }
    where_prop = {
        "type": "string",
        "title": "WHERE Clause",
        "default": "",
        "description": "Filter condition for update or delete (e.g. id = 1).",
    }
    params_prop = {
        "type": "array",
        "title": "Query Parameters",
        "default": [],
        "description": "List of parameter values for '?' parameter binding.",
    }
    max_rows_prop = {
        "type": "integer",
        "title": "Max Rows",
        "default": 1000,
        "minimum": 1,
        "maximum": 10000,
        "description": "Row cap, so a wide SELECT cannot exhaust memory. When the result is capped a trailing 'truncated' marker is returned.",
    }

    rows_out = {
        "type": "object",
        "properties": {
            "output": {
                "type": "array",
                "description": "SELECT returns one map per row; other statements return a rows_affected map. "
                               "When max_rows caps the result, a final {truncated: true, max_rows: n} map is appended.",
                "items": {"type": "object"},
            },
        },
        "required": ["output"],
    }
    write_out = {
        "type": "object",
        "properties": {
            "output": {
                "type": "array",
                "description": "Status entry with rows_affected, plus id when the driver reports one.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": ["integer", "null"], "description": "lastrowid, when available."},
                        "rows_affected": {"type": "integer"},
                        "status": {"type": "string", "enum": ["inserted", "updated", "deleted"]},
                    },
                },
            },
        },
        "required": ["output"],
    }

    return {
        "query": _operation(
            "query",
            "Execute Query",
            "Execute a SELECT statement and return rows as items.",
            {"query": query_prop, "parameters": params_prop, "max_rows": max_rows_prop},
            required=["query"],
            output_schema=rows_out,
            idempotency="idempotent",
            retryable=True,
        ),
        "insert": _operation(
            "insert",
            "Insert Row",
            "Insert a new record into an SQLite table.",
            {"table": table_prop, "data": data_prop},
            required=["table", "data"],
            output_schema=write_out,
            idempotency="non_idempotent",
            retryable=False,
        ),
        "update": _operation(
            "update",
            "Update Rows",
            "Update records in an SQLite table matching a condition.",
            {"table": table_prop, "data": data_prop, "where": where_prop},
            required=["table", "data", "where"],
            output_schema=write_out,
            idempotency="idempotent",
            retryable=False,
        ),
        "delete": _operation(
            "delete",
            "Delete Rows",
            "Delete records from an SQLite table matching a condition.",
            {"table": table_prop, "where": where_prop},
            required=["table", "where"],
            output_schema=write_out,
            idempotency="idempotent",
            retryable=False,
        ),
        "execute": _operation(
            "execute",
            "Execute DDL / DML",
            "Execute arbitrary DDL or DML statements (CREATE TABLE, ALTER, DROP, etc.).",
            {"query": query_prop},
            required=["query"],
            output_schema=rows_out,
            idempotency="conditionally_idempotent",
            retryable=False,
        ),
    }


def _sqlite_credentials() -> Dict[str, CredentialTypeV1]:
    return {
        "sqlite": CredentialTypeV1(
            type_key="sqlite",
            display_name="SQLite Connection",
            description="File path or in-memory database configuration for SQLite.",
            secret_fields=[],
            validation_schema={
                "type": "object",
                "properties": {
                    "database_path": {
                        "type": "string",
                        "title": "Database Path",
                        "default": ":memory:",
                        "description": "Absolute or workspace path to .db/.sqlite file, or ':memory:'.",
                    },
                },
                "required": ["database_path"],
            },
        )
    }


def build_sqlite_definition() -> ConnectorDefinitionV1:
    """Build the active ConnectorDefinitionV1 for SQLite."""
    return ConnectorDefinitionV1(
        connector_key=SQLITE_CONNECTOR_KEY,
        display_name="SQLite",
        description="Execute queries, insert, update, and manage data in SQLite databases.",
        category="database",
        connector_version=SQLITE_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_sqlite_operations(),
        triggers={},
        credential_types=_sqlite_credentials(),
        icon="database",
    )
