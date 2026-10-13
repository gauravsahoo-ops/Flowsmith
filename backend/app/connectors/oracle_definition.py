"""Oracle Database connector definition.

Clean-room versioned ConnectorDefinitionV1 for Oracle Database enterprise RDBMS.
Supports query execution, table operations, insert, update, delete, and schema introspection.
"""

from __future__ import annotations

from typing import Any, Dict
from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

ORACLE_CONNECTOR_KEY = "oracle"
ORACLE_CONNECTOR_VERSION = "1.0.0"
ORACLE_OPERATION_VERSION = "1.0.0"


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
        connector_key=ORACLE_CONNECTOR_KEY,
        connector_version=ORACLE_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=ORACLE_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="oracle",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["oracle"],
    )


def _oracle_operations() -> Dict[str, ConnectorOperationV1]:
    query_prop = {
        "type": "string",
        "title": "SQL Query",
        "default": "",
        "description": "SQL statement to execute (e.g., SELECT * FROM EMPLOYEES WHERE DEPT_ID = :1).",
    }
    table_prop = {
        "type": "string",
        "title": "Table Name",
        "default": "",
        "description": "Target Oracle table name.",
    }
    data_prop = {
        "type": "object",
        "title": "Row Data",
        "default": {},
        "description": "Column-to-value dictionary for insert or update.",
    }
    where_prop = {
        "type": "string",
        "title": "WHERE Clause",
        "default": "",
        "description": "Condition for update or delete (without 'WHERE' keyword).",
    }
    parameters_prop = {
        "type": "array",
        "title": "Parameters",
        "default": [],
        "description": "Bind variables for query execution.",
    }
    max_rows_prop = {
        "type": "integer",
        "title": "Max Rows",
        "default": 1000,
        "minimum": 1,
        "maximum": 10000,
        "description": "Maximum number of rows to return.",
    }

    query_out = {
        "type": "object",
        "properties": {
            "rows": {"type": "array", "items": {"type": "object"}},
            "row_count": {"type": "integer"},
        },
        "required": ["rows", "row_count"],
    }

    mutation_out = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["success"]},
            "affected_rows": {"type": "integer"},
        },
        "required": ["status", "affected_rows"],
    }

    tables_out = {
        "type": "object",
        "properties": {
            "tables": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["tables"],
    }

    return {
        "query": _operation(
            "query",
            "Execute Query",
            "Execute a SELECT statement against Oracle Database.",
            {"query": query_prop, "parameters": parameters_prop, "max_rows": max_rows_prop},
            ["query"],
            output_schema=query_out,
            retryable=True,
            idempotency="idempotent",
        ),
        "execute": _operation(
            "execute",
            "Execute Statement",
            "Execute an arbitrary SQL statement or DDL/DML.",
            {"query": query_prop, "parameters": parameters_prop},
            ["query"],
            output_schema=mutation_out,
            retryable=False,
            idempotency="non_idempotent",
        ),
        "insert": _operation(
            "insert",
            "Insert Row",
            "Insert a record into an Oracle table.",
            {"table": table_prop, "data": data_prop},
            ["table", "data"],
            output_schema=mutation_out,
            retryable=False,
            idempotency="non_idempotent",
        ),
        "update": _operation(
            "update",
            "Update Rows",
            "Update existing records in an Oracle table.",
            {"table": table_prop, "data": data_prop, "where": where_prop},
            ["table", "data"],
            output_schema=mutation_out,
            retryable=True,
            idempotency="idempotent",
        ),
        "delete": _operation(
            "delete",
            "Delete Rows",
            "Delete records from an Oracle table.",
            {"table": table_prop, "where": where_prop},
            ["table"],
            output_schema=mutation_out,
            retryable=True,
            idempotency="idempotent",
        ),
        "table_list": _operation(
            "table_list",
            "List Tables",
            "Introspect available tables in user schema.",
            {},
            [],
            output_schema=tables_out,
            retryable=True,
            idempotency="idempotent",
        ),
    }


def _oracle_credential_types() -> Dict[str, CredentialTypeV1]:
    return {
        "oracle": CredentialTypeV1(
            type_key="oracle",
            display_name="Oracle Database Connection",
            description="Connection parameters and credentials for Oracle Database.",
            secret_fields=["password", "wallet_password"],
            validation_schema={
                "type": "object",
                "properties": {
                    "host": {"type": "string", "title": "Host", "description": "Database server hostname or IP."},
                    "port": {"type": "integer", "title": "Port", "default": 1521},
                    "service_name": {"type": "string", "title": "Service Name", "default": ""},
                    "sid": {"type": "string", "title": "SID", "default": ""},
                    "username": {"type": "string", "title": "Username"},
                    "password": {"type": "string", "title": "Password"},
                    "schema": {"type": "string", "title": "Schema", "default": ""},
                },
                "required": ["host", "username", "password"],
            },
            encryption_required=True,
        )
    }


def build_oracle_definition() -> ConnectorDefinitionV1:
    """Construct version 1.0.0 Oracle Database connector definition."""
    return ConnectorDefinitionV1(
        connector_key=ORACLE_CONNECTOR_KEY,
        display_name="Oracle Database",
        description="Query, manage, and update records in Oracle Database enterprise instances.",
        category="database",
        connector_version=ORACLE_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_oracle_operations(),
        triggers={},
        credential_types=_oracle_credential_types(),
        metadata={
            "vendor": "Oracle Corporation",
            "dialect": "Oracle SQL",
        },
    )
