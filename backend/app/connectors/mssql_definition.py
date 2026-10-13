"""Microsoft SQL Server (MSSQL) connector definition.

Clean-room versioned ConnectorDefinitionV1 for Microsoft SQL Server / Azure SQL Database.
Covers SQL query execution, parameterized inserts, updates, deletes, and schema describe.
"""

from __future__ import annotations

from typing import Any, Dict
from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

MSSQL_CONNECTOR_KEY = "mssql"
MSSQL_CONNECTOR_VERSION = "1.0.0"
MSSQL_OPERATION_VERSION = "1.0.0"


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
        connector_key=MSSQL_CONNECTOR_KEY,
        connector_version=MSSQL_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=MSSQL_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="mssql",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["mssql"],
    )


def _mssql_operations() -> Dict[str, ConnectorOperationV1]:
    query_prop = {
        "type": "string",
        "title": "SQL Query",
        "default": "SELECT TOP 100 * FROM sys.tables",
        "description": "T-SQL query or statement to execute.",
    }
    table_prop = {
        "type": "string",
        "title": "Table Name",
        "default": "",
        "description": "Target SQL Server table name (e.g. dbo.Customers).",
    }
    data_prop = {
        "type": "object",
        "title": "Data / Row",
        "default": {},
        "description": "Column and value map for insert/update operations.",
    }
    where_prop = {
        "type": "string",
        "title": "WHERE Clause",
        "default": "",
        "description": "Filter condition for update or delete (e.g. Id = 101).",
    }
    params_prop = {
        "type": "array",
        "title": "Query Parameters",
        "default": [],
        "description": "Positional or named parameters for parameterized queries.",
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
                "description": "One entry per result set: row maps for SELECT, or a rows_affected entry otherwise. "
                               "When max_rows caps the result, a final {truncated: true, max_rows: n} map is appended.",
                "items": {"type": "object"},
            },
        },
        "required": ["output"],
    }
    describe_out = {
        "type": "object",
        "properties": {
            "output": {
                "type": "array",
                "description": "Column metadata for the table: name, type, nullable, key, default.",
                "items": {"type": "object"},
            },
        },
        "required": ["output"],
    }

    return {
        "query": _operation(
            "query",
            "Execute Query",
            "Execute a T-SQL query and return resulting rows as items.",
            {"query": query_prop, "parameters": params_prop, "max_rows": max_rows_prop},
            required=["query"],
            output_schema=rows_out,
            idempotency="idempotent",
            retryable=True,
        ),
        "insert": _operation(
            "insert",
            "Insert Row",
            "Insert a new record into a specified SQL Server table.",
            {"table": table_prop, "data": data_prop},
            required=["table", "data"],
            output_schema=rows_out,
            idempotency="non_idempotent",
            retryable=False,
        ),
        "update": _operation(
            "update",
            "Update Rows",
            "Update existing records in a table matching a condition.",
            {"table": table_prop, "data": data_prop, "where": where_prop},
            required=["table", "data", "where"],
            output_schema=rows_out,
            idempotency="idempotent",
            retryable=False,
        ),
        "delete": _operation(
            "delete",
            "Delete Rows",
            "Delete records from a table matching a condition.",
            {"table": table_prop, "where": where_prop},
            required=["table", "where"],
            output_schema=rows_out,
            idempotency="idempotent",
            retryable=False,
        ),
        "describe": _operation(
            "describe",
            "Describe Table",
            "Retrieve column metadata and schema details for a table.",
            {"table": table_prop},
            required=["table"],
            output_schema=describe_out,
            idempotency="idempotent",
            retryable=True,
        ),
    }


def _mssql_credentials() -> Dict[str, CredentialTypeV1]:
    return {
        "mssql": CredentialTypeV1(
            type_key="mssql",
            display_name="Microsoft SQL Server Credentials",
            description="Connection parameters for SQL Server / Azure SQL.",
            secret_fields=["password"],
            validation_schema={
                "type": "object",
                "properties": {
                    "host": {"type": "string", "title": "Host", "default": "localhost"},
                    "port": {"type": "integer", "title": "Port", "default": 1433},
                    "database": {"type": "string", "title": "Database Name"},
                    "username": {"type": "string", "title": "User / Login"},
                    "password": {"type": "string", "title": "Password", "format": "password"},
                    "encrypt": {"type": "boolean", "title": "Encrypt (TLS)", "default": True},
                    "trustServerCertificate": {"type": "boolean", "title": "Trust Server Certificate", "default": True},
                },
                "required": ["host", "database", "username", "password"],
            },
        )
    }


def build_mssql_definition() -> ConnectorDefinitionV1:
    """Build the active ConnectorDefinitionV1 for Microsoft SQL Server."""
    return ConnectorDefinitionV1(
        connector_key=MSSQL_CONNECTOR_KEY,
        display_name="Microsoft SQL Server",
        description="Query, insert, update, and manage data in Microsoft SQL Server and Azure SQL Database.",
        category="database",
        connector_version=MSSQL_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_mssql_operations(),
        triggers={},
        credential_types=_mssql_credentials(),
        icon="database",
    )
