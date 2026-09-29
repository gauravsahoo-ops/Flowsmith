"""Snowflake Data Cloud connector definition (Phase 39)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

SNOWFLAKE_CONNECTOR_KEY = "snowflake"
SNOWFLAKE_CONNECTOR_VERSION = "1.0.0"
SNOWFLAKE_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=SNOWFLAKE_CONNECTOR_KEY,
        connector_version=SNOWFLAKE_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=SNOWFLAKE_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="snowflake",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["snowflake"],
    )


def build_snowflake_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=SNOWFLAKE_CONNECTOR_KEY,
        display_name="Snowflake Data Cloud",
        description="Execute SQL queries, fetch partition results, and inspect database metadata on Snowflake Data Cloud via SQL API v2.",
        category="database",
        connector_version=SNOWFLAKE_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "execute_query": _operation(
                "execute_query", "Execute SQL Query", "Execute any SQL query, DDL, or DML statement on Snowflake.",
                {
                    "statement": {"type": "string", "title": "SQL Statement"},
                    "warehouse": {"type": "string", "title": "Warehouse"},
                    "database": {"type": "string", "title": "Database"},
                    "schema": {"type": "string", "title": "Schema"},
                    "role": {"type": "string", "title": "Role"},
                    "wait_for_completion": {"type": "boolean", "title": "Wait for completion", "default": True},
                },
                ["statement"],
                retryable=False, idempotency="non_idempotent",
            ),
            "get_query_results": _operation(
                "get_query_results", "Get Query Results", "Retrieve results or specific partition for an executed statement.",
                {
                    "statement_handle": {"type": "string", "title": "Statement Handle"},
                    "partition": {"type": "integer", "title": "Partition Index", "default": 0},
                },
                ["statement_handle"],
            ),
            "cancel_query": _operation(
                "cancel_query", "Cancel Query", "Cancel an in-flight asynchronous statement.",
                {
                    "statement_handle": {"type": "string", "title": "Statement Handle"},
                },
                ["statement_handle"],
            ),
            "describe_table": _operation(
                "describe_table", "Describe Table Schema", "Retrieve column definitions and data types for dynamic schema introspection.",
                {
                    "table_name": {"type": "string", "title": "Table Name"},
                    "database": {"type": "string", "title": "Database"},
                    "schema": {"type": "string", "title": "Schema"},
                },
                ["table_name"],
            ),
            "list_tables": _operation(
                "list_tables", "List Tables", "Discover tables in a Snowflake database or schema.",
                {
                    "database": {"type": "string", "title": "Database"},
                    "schema": {"type": "string", "title": "Schema"},
                },
                [],
            ),
        },
        triggers={},
        credential_types={
            "snowflake": CredentialTypeV1(
                type_key="snowflake",
                display_name="Snowflake SQL API Credentials",
                description="Snowflake account identifier and Bearer token / Keypair JWT.",
                secret_fields=["token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "account": {"type": "string", "title": "Account Identifier (e.g. xy12345.us-east-1)"},
                        "token": {"type": "string", "title": "Bearer Token / Keypair JWT"},
                        "warehouse": {"type": "string", "title": "Default Warehouse"},
                        "database": {"type": "string", "title": "Default Database"},
                        "schema": {"type": "string", "title": "Default Schema"},
                        "role": {"type": "string", "title": "Default Role"},
                    },
                    "required": ["account", "token"],
                },
                encryption_required=True,
            )
        },
    )
