"""Google Cloud BigQuery connector definition (Phase 40)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

BIGQUERY_CONNECTOR_KEY = "bigquery"
BIGQUERY_CONNECTOR_VERSION = "1.0.0"
BIGQUERY_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=BIGQUERY_CONNECTOR_KEY,
        connector_version=BIGQUERY_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=BIGQUERY_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="bigquery",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["bigquery"],
    )


def build_bigquery_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=BIGQUERY_CONNECTOR_KEY,
        display_name="Google BigQuery",
        description="Run SQL analytics, discover datasets, and inspect table schemas on Google Cloud BigQuery.",
        category="database",
        connector_version=BIGQUERY_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "query": _operation(
                "query", "Execute SQL Query", "Run standard SQL query across BigQuery datasets.",
                {
                    "query": {"type": "string", "title": "SQL Query"},
                    "max_results": {"type": "integer", "title": "Max Results", "default": 100},
                    "use_legacy_sql": {"type": "boolean", "title": "Use Legacy SQL", "default": False},
                },
                ["query"],
                retryable=False, idempotency="non_idempotent",
            ),
            "get_query_results": _operation(
                "get_query_results", "Get Query Results", "Retrieve paginated results for an executed job ID.",
                {
                    "job_id": {"type": "string", "title": "Job ID"},
                    "page_token": {"type": "string", "title": "Page Token"},
                    "max_results": {"type": "integer", "title": "Max Results", "default": 100},
                },
                ["job_id"],
            ),
            "list_datasets": _operation(
                "list_datasets", "List Datasets", "List all datasets in the project.",
                {
                    "max_results": {"type": "integer", "title": "Max Results", "default": 50},
                    "page_token": {"type": "string", "title": "Page Token"},
                },
                [],
            ),
            "list_tables": _operation(
                "list_tables", "List Tables", "List all tables within a BigQuery dataset.",
                {
                    "dataset_id": {"type": "string", "title": "Dataset ID"},
                    "max_results": {"type": "integer", "title": "Max Results", "default": 50},
                    "page_token": {"type": "string", "title": "Page Token"},
                },
                ["dataset_id"],
            ),
            "get_table": _operation(
                "get_table", "Get Table Metadata", "Inspect schema fields and column definitions for a table.",
                {
                    "dataset_id": {"type": "string", "title": "Dataset ID"},
                    "table_id": {"type": "string", "title": "Table ID"},
                },
                ["dataset_id", "table_id"],
            ),
        },
        triggers={},
        credential_types={
            "bigquery": CredentialTypeV1(
                type_key="bigquery",
                display_name="Google Cloud BigQuery Credentials",
                description="Google Cloud Project ID and OAuth2 / Service Account access token.",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "title": "GCP Project ID"},
                        "access_token": {"type": "string", "title": "Access Token (OAuth2 or Service Account)"},
                    },
                    "required": ["project_id", "access_token"],
                },
                encryption_required=True,
            )
        },
    )
