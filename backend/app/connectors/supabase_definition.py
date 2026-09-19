"""Supabase connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorCategory,
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

SUPABASE_CONNECTOR_KEY = "supabase"
SUPABASE_CONNECTOR_VERSION = "1.0.0"


def build_supabase_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=SUPABASE_CONNECTOR_KEY,
        display_name="Supabase",
        description="Query tables, insert/update/delete records, and call RPC functions in Supabase.",
        category=ConnectorCategory.API.value,
        connector_version=SUPABASE_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        supported_node_types=["supabase"],
        credential_types={
            "supabase": CredentialTypeV1(
                type_key="supabase",
                display_name="Supabase API Credentials",
                description="Supabase project URL and service role / anon key.",
                secret_fields=["service_role_key", "anon_key"],
                validation_schema={
                    "type": "object",
                    "required": ["url", "service_role_key"],
                    "properties": {
                        "url": {"type": "string", "title": "Project URL", "format": "uri"},
                        "service_role_key": {"type": "string", "title": "Service Role Key / Secret Key", "format": "password"},
                        "anon_key": {"type": "string", "title": "Anon Key (Optional)", "format": "password"},
                    },
                },
                encryption_required=True,
            )
        },
        operations={
            "select_rows": ConnectorOperationV1(
                connector_key=SUPABASE_CONNECTOR_KEY,
                connector_version=SUPABASE_CONNECTOR_VERSION,
                operation_key="select_rows",
                operation_version="1.0.0",
                display_name="Select Rows",
                description="Query rows from a table with filters, column selection, and limits.",
                input_schema={
                    "type": "object",
                    "required": ["table"],
                    "properties": {
                        "table": {"type": "string", "title": "Table Name"},
                        "select": {"type": "string", "title": "Select Columns", "default": "*"},
                        "limit": {"type": "integer", "title": "Limit", "default": 100},
                        "filter": {"type": "object", "title": "PostgREST Filters"},
                    },
                },
                output_schema={"type": "object", "properties": {"data": {"type": "array"}}},
                credential_require="supabase",
                retryable=True,
                idempotency="idempotent",
                node_types=["supabase"],
            ),
            "insert_row": ConnectorOperationV1(
                connector_key=SUPABASE_CONNECTOR_KEY,
                connector_version=SUPABASE_CONNECTOR_VERSION,
                operation_key="insert_row",
                operation_version="1.0.0",
                display_name="Insert Row",
                description="Insert one or more records into a table.",
                input_schema={
                    "type": "object",
                    "required": ["table", "data"],
                    "properties": {
                        "table": {"type": "string", "title": "Table Name"},
                        "data": {"type": "object", "title": "Row Data / Payload"},
                    },
                },
                output_schema={"type": "object", "properties": {"data": {"type": "array"}}},
                credential_require="supabase",
                retryable=False,
                idempotency="non_idempotent",
                node_types=["supabase"],
            ),
            "update_row": ConnectorOperationV1(
                connector_key=SUPABASE_CONNECTOR_KEY,
                connector_version=SUPABASE_CONNECTOR_VERSION,
                operation_key="update_row",
                operation_version="1.0.0",
                display_name="Update Row",
                description="Update records matching a column filter.",
                input_schema={
                    "type": "object",
                    "required": ["table", "match_column", "match_value", "data"],
                    "properties": {
                        "table": {"type": "string", "title": "Table Name"},
                        "match_column": {"type": "string", "title": "Match Column", "default": "id"},
                        "match_value": {"type": "string", "title": "Match Value"},
                        "data": {"type": "object", "title": "Updated Values"},
                    },
                },
                output_schema={"type": "object", "properties": {"data": {"type": "array"}}},
                credential_require="supabase",
                retryable=True,
                idempotency="idempotent",
                node_types=["supabase"],
            ),
            "delete_row": ConnectorOperationV1(
                connector_key=SUPABASE_CONNECTOR_KEY,
                connector_version=SUPABASE_CONNECTOR_VERSION,
                operation_key="delete_row",
                operation_version="1.0.0",
                display_name="Delete Row",
                description="Delete records matching a column filter.",
                input_schema={
                    "type": "object",
                    "required": ["table", "match_column", "match_value"],
                    "properties": {
                        "table": {"type": "string", "title": "Table Name"},
                        "match_column": {"type": "string", "title": "Match Column", "default": "id"},
                        "match_value": {"type": "string", "title": "Match Value"},
                    },
                },
                output_schema={"type": "object", "properties": {"data": {"type": "array"}}},
                credential_require="supabase",
                retryable=True,
                idempotency="idempotent",
                node_types=["supabase"],
            ),
            "rpc_call": ConnectorOperationV1(
                connector_key=SUPABASE_CONNECTOR_KEY,
                connector_version=SUPABASE_CONNECTOR_VERSION,
                operation_key="rpc_call",
                operation_version="1.0.0",
                display_name="Call RPC Function",
                description="Call a Supabase database function / RPC endpoint.",
                input_schema={
                    "type": "object",
                    "required": ["function_name"],
                    "properties": {
                        "function_name": {"type": "string", "title": "Function Name"},
                        "args": {"type": "object", "title": "Function Arguments"},
                    },
                },
                output_schema={"type": "object", "properties": {"data": {"type": "object"}}},
                credential_require="supabase",
                retryable=True,
                idempotency="idempotent",
                node_types=["supabase"],
            ),
        },
        triggers={},
    )
