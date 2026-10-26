"""Native REST connectors for catalog conversion batch 7.

This batch is intentionally report-only. Every catalog key grouped here uses a
request-signing authentication scheme that the shared
:class:`~app.connectors.vendor_rest.VendorRESTConnector` does not implement:

* AWS IAM, SES, SNS, and SQS use the AWS query protocol (a form-encoded
  ``Action``/``Version`` body) plus AWS Signature Version 4.
* AWS Lambda, Rekognition, Textract, and Transcribe use AWS Signature Version 4,
  region-selected endpoints, and (for the last three) an ``X-Amz-Target``
  header.
* AWS S3 uses AWS Signature Version 4, bucket-scoped hosts, XML responses, and
  binary object bodies. Flowsmith already ships a dedicated native S3
  connector with a tested SigV4 signer.
* Azure Cosmos DB's shared-key credential signs every request with an
  HMAC-SHA256 token derived from the HTTP verb, resource link, and
  ``x-ms-date``.

Publishing a :class:`VendorSpec` with bearer/basic/header auth for any of these
keys would send unsigned requests and return authentication failures. Instead,
each key is listed in :data:`UNSUPPORTED_BATCH7_KEYS` with the specific reason,
and :func:`build_batch7_connectors` returns no pairs. No endpoint or signature
is invented. Converting these keys requires a signer-aware connector (or an
auth-provider hook in ``VendorRESTConnector``), not just another ``VendorSpec``.
"""

from __future__ import annotations

from typing import Any

# n8n reference implementations inspected:
# Aws/IAM/AwsIam.node.ts, Aws/AwsLambda.node.ts,
# Aws/Rekognition/AwsRekognition.node.ts, Aws/S3/V2/AwsS3V2.node.ts,
# Aws/SES/AwsSes.node.ts, Aws/AwsSns.node.ts, Aws/SQS/AwsSqs.node.ts,
# Aws/Textract/AwsTextract.node.ts, Aws/Transcribe/AwsTranscribe.node.ts,
# and Microsoft/AzureCosmosDb/transport/index.ts.

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)
from app.connectors.vendor_rest import VendorOperation, VendorRESTConnector, VendorSpec

BATCH7_CATALOG_KEYS = frozenset({
    "aws_iam",
    "aws_lambda",
    "aws_rekognition",
    "aws_s3",
    "aws_ses",
    "aws_sns",
    "aws_sqs",
    "aws_textract",
    "aws_transcribe",
    "azure_cosmos_db",
})

# Keys intentionally left out of build_batch7_connectors(). Keeping the
# reasons next to the empty spec table makes the gap explicit instead of
# shipping connector definitions whose operations cannot actually authenticate.
UNSUPPORTED_BATCH7_KEYS: dict[str, str] = {
    "aws_iam": (
        "AWS IAM uses the AWS query protocol (a form-encoded Action/Version body) "
        "and requires AWS Signature Version 4 on every request. VendorRESTConnector "
        "has no SigV4 auth kind and sends JSON bodies, so a VendorSpec here would "
        "issue unsigned and malformed requests."
    ),
    "aws_lambda": (
        "AWS Lambda Invoke requires AWS Signature Version 4, a region-selected "
        "endpoint, and the X-Amz-Invocation-Type header. VendorRESTConnector has "
        "no SigV4 auth kind or per-operation header support."
    ),
    "aws_rekognition": (
        "AWS Rekognition requires AWS Signature Version 4 plus an X-Amz-Target "
        "header and application/x-amz-json-1.1 payloads. VendorRESTConnector has "
        "no SigV4 auth kind or X-Amz-Target support."
    ),
    "aws_s3": (
        "AWS S3 requires AWS Signature Version 4, bucket-scoped hosts, XML "
        "responses, and binary object bodies. VendorRESTConnector has no SigV4 auth "
        "kind and only sends JSON bodies. Flowsmith already provides a dedicated "
        "native S3 connector (key 's3', node type 'aws_s3') with a tested SigV4 "
        "signer, so a second VendorRESTConnector here would duplicate it."
    ),
    "aws_ses": (
        "AWS SES uses the AWS query protocol (a form-encoded Action/Version body) "
        "and requires AWS Signature Version 4. VendorRESTConnector has neither a "
        "SigV4 auth kind nor query-protocol body encoding."
    ),
    "aws_sns": (
        "AWS SNS uses the AWS query protocol (a form-encoded Action/Version body) "
        "and requires AWS Signature Version 4. VendorRESTConnector has neither a "
        "SigV4 auth kind nor query-protocol body encoding."
    ),
    "aws_sqs": (
        "AWS SQS uses the AWS query protocol (Action parameters in the query "
        "string or form body) and requires AWS Signature Version 4. "
        "VendorRESTConnector cannot sign requests or encode query-protocol bodies."
    ),
    "aws_textract": (
        "AWS Textract requires AWS Signature Version 4 plus an X-Amz-Target "
        "header (for example Textract.AnalyzeExpense) and application/x-amz-json-1.1 "
        "payloads. VendorRESTConnector has no SigV4 auth kind or X-Amz-Target "
        "support."
    ),
    "aws_transcribe": (
        "AWS Transcribe requires AWS Signature Version 4 plus an X-Amz-Target "
        "header (for example Transcribe.StartTranscriptionJob) and "
        "application/x-amz-json-1.1 payloads. VendorRESTConnector has no SigV4 auth "
        "kind or X-Amz-Target support."
    ),
    "azure_cosmos_db": (
        "Azure Cosmos DB's shared-key credential computes an HMAC-SHA256 signature "
        "over the HTTP verb, resource type, resource link, and x-ms-date for every "
        "request. VendorRESTConnector has no shared-key signing auth kind, and a "
        "static Authorization header cannot replace the per-request signature."
    ),
}

# Empty by design. A VendorSpec is added here only when its auth scheme can be
# expressed by VendorRESTConnector (bearer, basic, header, query, or none).
VENDOR_SPECS: dict[str, VendorSpec] = {}


def _title(field: str) -> str:
    return field.replace("_", " ").title()


def _credential_schema(spec: VendorSpec) -> dict[str, Any]:
    """Build the JSON schema shown for this connector's credential type."""
    fields = list(dict.fromkeys((*spec.credential_fields, *spec.extra_required)))
    properties: dict[str, Any] = {}
    for field in fields:
        prop: dict[str, Any] = {"type": "string", "title": _title(field)}
        if field in spec.credential_fields:
            prop["format"] = "password"
        properties[field] = prop
    return {
        "type": "object",
        "properties": properties,
        "required": fields,
    }


def _operation_definition(spec: VendorSpec, op: VendorOperation) -> ConnectorOperationV1:
    required_params = list(dict.fromkeys((*spec.extra_required, *op.requires)))
    param_properties = {name: {"type": "string"} for name in required_params}
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "params": {
                "type": "object",
                "properties": param_properties,
                "additionalProperties": True,
            },
            "body": {"type": "object", "additionalProperties": True},
            "timeout_seconds": {
                "type": "number",
                "minimum": 1,
                "maximum": 300,
                "default": 30,
            },
        },
    }
    if required_params:
        input_schema["properties"]["params"]["required"] = required_params
        input_schema["required"] = ["params"]
    return ConnectorOperationV1(
        connector_key=spec.key,
        connector_version="1.0.0",
        operation_key=op.key,
        operation_version="1.0.0",
        display_name=op.display_name,
        description=op.description or f"{op.display_name} for {spec.display_name}.",
        input_schema=input_schema,
        output_schema={"type": "object"},
        credential_require=spec.key,
        retryable=op.retryable,
        idempotency=op.idempotency,
        node_types=[spec.key],
    )


def _build_definition(spec: VendorSpec) -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=spec.key,
        display_name=spec.display_name,
        description=spec.description,
        category=spec.category,
        connector_version="1.0.0",
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            key: _operation_definition(spec, op)
            for key, op in spec.operations.items()
        },
        triggers={},
        credential_types={
            spec.key: CredentialTypeV1(
                type_key=spec.key,
                display_name=f"{spec.display_name} Credentials",
                description=f"Credentials for {spec.display_name}.",
                secret_fields=list(spec.credential_fields),
                validation_schema=_credential_schema(spec),
                encryption_required=True,
            )
        },
        metadata={
            "implementation": "native",
            "batch": "catalog_conversion_7",
        },
    )


def build_batch7_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Return the batch 7 native connector/definition pairs that can run.

    The list is empty because all ten catalog keys in this batch require
    request-signing auth that VendorRESTConnector does not implement. See
    :data:`UNSUPPORTED_BATCH7_KEYS` for the per-key reason.
    """
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
