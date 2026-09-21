"""AWS S3 / Object Storage connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorCategory,
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

S3_CONNECTOR_KEY = "s3"
S3_CONNECTOR_VERSION = "1.0.0"


def build_s3_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=S3_CONNECTOR_KEY,
        display_name="AWS S3 / Object Storage",
        description="Upload, download, list, and delete files in AWS S3, Cloudflare R2, MinIO, or Wasabi.",
        category=ConnectorCategory.API.value,
        connector_version=S3_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        credential_types={
            "aws_s3": CredentialTypeV1(
                type_key="aws_s3",
                display_name="AWS S3 / S3-Compatible Credentials",
                description="AWS Access Key ID, Secret Key, Region, and optional custom endpoint.",
                secret_fields=["secret_access_key"],
                validation_schema={
                    "type": "object",
                    "required": ["access_key_id", "secret_access_key", "bucket_name"],
                    "properties": {
                        "access_key_id": {"type": "string", "title": "Access Key ID"},
                        "secret_access_key": {"type": "string", "title": "Secret Access Key", "format": "password"},
                        "bucket_name": {"type": "string", "title": "Default Bucket Name"},
                        "region": {"type": "string", "title": "AWS Region (e.g. us-east-1)", "default": "us-east-1"},
                        "endpoint_url": {"type": "string", "title": "Custom Endpoint URL (e.g. for MinIO / Cloudflare R2)"},
                    },
                },
                encryption_required=True,
            )
        },
        operations={
            "upload_file": ConnectorOperationV1(
                connector_key=S3_CONNECTOR_KEY,
                connector_version=S3_CONNECTOR_VERSION,
                operation_key="upload_file",
                operation_version="1.0.0",
                display_name="Upload File / Put Object",
                description="Upload a text or binary payload to an S3 bucket.",
                input_schema={
                    "type": "object",
                    "required": ["key", "content"],
                    "properties": {
                        "bucket": {"type": "string", "title": "Bucket Name (Optional override)"},
                        "key": {"type": "string", "title": "Object Key / Path (e.g. uploads/doc.pdf)"},
                        "content": {"type": "string", "title": "File Content / Data"},
                        "content_type": {"type": "string", "title": "Content Type", "default": "application/octet-stream"},
                    },
                },
                output_schema={"type": "object", "properties": {"status": {"type": "string"}, "key": {"type": "string"}}},
                credential_require="aws_s3",
                retryable=True,
                idempotency="idempotent",
                node_types=["s3", "aws_s3"],
            ),
            "download_file": ConnectorOperationV1(
                connector_key=S3_CONNECTOR_KEY,
                connector_version=S3_CONNECTOR_VERSION,
                operation_key="download_file",
                operation_version="1.0.0",
                display_name="Download File / Get Object",
                description="Retrieve a file or pre-signed URL from an S3 bucket.",
                input_schema={
                    "type": "object",
                    "required": ["key"],
                    "properties": {
                        "bucket": {"type": "string", "title": "Bucket Name (Optional override)"},
                        "key": {"type": "string", "title": "Object Key / Path"},
                    },
                },
                output_schema={"type": "object", "properties": {"status": {"type": "string"}, "url": {"type": "string"}}},
                credential_require="aws_s3",
                retryable=True,
                idempotency="idempotent",
                node_types=["s3", "aws_s3"],
            ),
            "list_objects": ConnectorOperationV1(
                connector_key=S3_CONNECTOR_KEY,
                connector_version=S3_CONNECTOR_VERSION,
                operation_key="list_objects",
                operation_version="1.0.0",
                display_name="List Objects",
                description="List files and prefixes in an S3 bucket.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "bucket": {"type": "string", "title": "Bucket Name (Optional override)"},
                        "prefix": {"type": "string", "title": "Prefix / Folder (Optional)"},
                    },
                },
                output_schema={"type": "object", "properties": {"objects": {"type": "array"}}},
                credential_require="aws_s3",
                retryable=True,
                idempotency="idempotent",
                node_types=["s3", "aws_s3"],
            ),
            "delete_object": ConnectorOperationV1(
                connector_key=S3_CONNECTOR_KEY,
                connector_version=S3_CONNECTOR_VERSION,
                operation_key="delete_object",
                operation_version="1.0.0",
                display_name="Delete Object",
                description="Delete a file from an S3 bucket.",
                input_schema={
                    "type": "object",
                    "required": ["key"],
                    "properties": {
                        "bucket": {"type": "string", "title": "Bucket Name (Optional override)"},
                        "key": {"type": "string", "title": "Object Key / Path"},
                    },
                },
                output_schema={"type": "object", "properties": {"deleted": {"type": "boolean"}}},
                credential_require="aws_s3",
                retryable=True,
                idempotency="idempotent",
                node_types=["s3", "aws_s3"],
            ),
        },
        triggers={},
    )
