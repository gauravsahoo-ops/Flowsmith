"""PostgreSQL connector definition (Phase 11 business connectors).

Versioned ConnectorDefinitionV1 for the Postgres connector:

1. query       - run SELECT-like statements, one row per output item
2. execute     - run INSERT/UPDATE/DDL, return affected rows
3. insert_rows - bulk-insert parameterised rows into a table
4. list_tables - enumerate tables in the target schema
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

POSTGRES_CONNECTOR_KEY = "postgres"
POSTGRES_CONNECTOR_VERSION = "1.0.0"
POSTGRES_OPERATION_VERSION = "1.0.0"

_SQL_PROP = {"type": "string", "title": "SQL", "description": "SQL statement (:name binds parameters)."}
_PARAMS_PROP = {
    "type": "object", "title": "Parameters",
    "description": 'Bound parameter values, e.g. {"status": "active"}.',
}


def _operation(
    key: str,
    display_name: str,
    description: str,
    input_properties: dict,
    required: list[str],
    output_schema: dict,
    *,
    retryable: bool = False,
    idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=POSTGRES_CONNECTOR_KEY,
        connector_version=POSTGRES_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=POSTGRES_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="postgres",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["postgres"],
    )


def _postgres_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "query": _operation(
            "query", "Query",
            "Run a SELECT and return the result rows (capped at 1000).",
            {"sql": _SQL_PROP, "params": _PARAMS_PROP},
            ["sql"],
            {
                "type": "object",
                "properties": {
                    "rows": {"type": "array", "items": {"type": "object"}},
                    "count": {"type": "integer"},
                },
            },
            retryable=True,
        ),
        "execute": _operation(
            "execute", "Execute",
            "Run an INSERT/UPDATE/DELETE/DDL statement and report affected rows.",
            {"sql": _SQL_PROP, "params": _PARAMS_PROP},
            ["sql"],
            {"type": "object", "properties": {"affected_rows": {"type": "integer"}}},
            retryable=True,
            idempotency="non_idempotent",
        ),
        "insert_rows": _operation(
            "insert_rows", "Insert Rows",
            "Bulk-insert rows into a table (columns taken from the first row).",
            {
                "table": {"type": "string", "title": "Table name"},
                "rows": {"type": "array", "title": "Rows", "items": {"type": "object"}},
            },
            ["table", "rows"],
            {"type": "object", "properties": {"inserted": {"type": "integer"}}},
            retryable=False,
            idempotency="non_idempotent",
        ),
        "list_tables": _operation(
            "list_tables", "List Tables",
            "List table names visible to the credential.",
            {},
            [],
            {
                "type": "object",
                "properties": {
                    "tables": {"type": "array", "items": {"type": "string"}},
                    "count": {"type": "integer"},
                },
            },
            retryable=True,
        ),
    }


def _postgres_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "postgres": CredentialTypeV1(
            type_key="postgres",
            display_name="PostgreSQL",
            description=(
                "PostgreSQL connection string (dsn), e.g. "
                "postgresql://user:password@host:5432/dbname. Stored encrypted."
            ),
            secret_fields=["dsn"],
            validation_schema={
                "type": "object",
                "properties": {
                    "dsn": {"type": "string", "title": "Connection string"},
                },
                "required": ["dsn"],
            },
            encryption_required=True,
        )
    }


def build_postgres_definition() -> ConnectorDefinitionV1:
    """Build the PostgreSQL connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=POSTGRES_CONNECTOR_KEY,
        display_name="PostgreSQL",
        description="Query and write to PostgreSQL databases via SQLAlchemy (parameterised statements).",
        category="database",
        connector_version=POSTGRES_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_postgres_operations(),
        triggers={},
        credential_types=_postgres_credential_type(),
        metadata={
            "initial_operations": ["query", "execute", "insert_rows", "list_tables"],
            "auth": "connection string (dsn) stored encrypted",
        },
        icon="postgres",
    )
