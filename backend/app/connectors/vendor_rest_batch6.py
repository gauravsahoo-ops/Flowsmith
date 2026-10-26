"""Native REST connectors for catalog conversion batch 6.

Only vendors that expose a fixed-host HTTP API and use an auth mechanism
supported by :class:`VendorRESTConnector` are implemented here. Catalog keys
that are local transforms, message-queue protocols, or require AWS Signature
Version 4 are listed in :data:`UNSUPPORTED_BATCH6_KEYS` with the reason they
were not converted. No placeholder endpoints are invented for those keys.
"""

from __future__ import annotations

from typing import Any

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)
from app.connectors.vendor_rest import VendorOperation, VendorRESTConnector, VendorSpec

BATCH6_CATALOG_KEYS = frozenset({
    "active_campaign",
    "ai_transform",
    "amqp",
    "api_template_io",
    "autopilot",
    "aws_certificate_manager",
    "aws_cognito",
    "aws_comprehend",
    "aws_dynamo_d_b",
    "aws_elb",
})

# Keys intentionally left out of build_batch6_connectors(). Keeping the
# reasons next to the implemented specs makes the gap explicit instead of
# shipping a connector definition whose operations cannot actually run.
UNSUPPORTED_BATCH6_KEYS: dict[str, str] = {
    "ai_transform": (
        "n8n's AI Transform node runs locally generated JavaScript in its task-runner "
        "sandbox; it has no vendor REST host, credentials, or HTTP operations."
    ),
    "amqp": (
        "n8n's AMQP Sender publishes AMQP 1.0 messages over TCP to a user-supplied "
        "broker via rhea; there is no fixed-host REST API for VendorRESTConnector."
    ),
    "aws_certificate_manager": (
        "AWS Certificate Manager requires AWS Signature Version 4 request signing and "
        "region endpoint selection; VendorRESTConnector has no SigV4 auth kind."
    ),
    "aws_cognito": (
        "AWS Cognito's user-pool API requires AWS Signature Version 4 signing plus an "
        "AWSCognitoIdentityProviderService X-Amz-Target; VendorRESTConnector has no "
        "SigV4 auth kind."
    ),
    "aws_comprehend": (
        "AWS Comprehend requires AWS Signature Version 4 request signing plus a "
        "Comprehend_20171127 X-Amz-Target; VendorRESTConnector has no SigV4 auth kind."
    ),
    "aws_dynamo_d_b": (
        "AWS DynamoDB requires AWS Signature Version 4 request signing plus a "
        "DynamoDB_20120810 X-Amz-Target; VendorRESTConnector has no SigV4 auth kind."
    ),
    "aws_elb": (
        "AWS Elastic Load Balancing uses the AWS query protocol with Signature Version 4 "
        "and region-specific endpoints; VendorRESTConnector has no SigV4 auth kind."
    ),
}

VENDOR_SPECS: dict[str, VendorSpec] = {
    "active_campaign": VendorSpec(
        key="active_campaign",
        display_name="ActiveCampaign",
        description="ActiveCampaign contacts, deals, lists, and tags.",
        category="marketing",
        # ActiveCampaign API v3 is served from an account-specific subdomain.
        # The domain itself is fixed; account is the subdomain only.
        base_url="https://{account}.api-us1.com/api/3",
        auth_kind="header",
        auth_header="Api-Token",
        credential_fields=("api_key",),
        extra_required=("account",),
        operations={
            "list_contacts": VendorOperation(
                "list_contacts", "List Contacts", "GET", "/contacts",
                description="List contacts; pagination and filters go in payload.params.",
            ),
            "get_contact": VendorOperation(
                "get_contact", "Get Contact", "GET", "/contacts/{contact_id}", ("contact_id",),
            ),
            "create_contact": VendorOperation(
                "create_contact", "Create Contact", "POST", "/contacts", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a contact; body must be wrapped as {\"contact\": {...}}.",
            ),
            "sync_contact": VendorOperation(
                "sync_contact", "Create or Update Contact", "POST", "/contact/sync", (),
                retryable=False, idempotency="non_idempotent",
                description="Create or update a contact by email; body is {\"contact\": {...}}.",
            ),
            "update_contact": VendorOperation(
                "update_contact", "Update Contact", "PUT", "/contacts/{contact_id}", ("contact_id",),
                description="Update a contact; body is {\"contact\": {...}}.",
            ),
            "delete_contact": VendorOperation(
                "delete_contact", "Delete Contact", "DELETE", "/contacts/{contact_id}", ("contact_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "list_lists": VendorOperation("list_lists", "List Lists", "GET", "/lists"),
            "list_deals": VendorOperation("list_deals", "List Deals", "GET", "/deals"),
            "create_deal": VendorOperation(
                "create_deal", "Create Deal", "POST", "/deals", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a deal; body is {\"deal\": {...}}.",
            ),
        },
    ),
    "api_template_io": VendorSpec(
        key="api_template_io",
        display_name="APITemplate.io",
        description="APITemplate.io PDF and image generation from templates.",
        category="marketing",
        base_url="https://api.apitemplate.io/v1",
        auth_kind="header",
        auth_header="X-API-KEY",
        credential_fields=("api_key",),
        operations={
            "get_account": VendorOperation(
                "get_account", "Get Account Information", "GET", "/account-information",
            ),
            "list_templates": VendorOperation(
                "list_templates", "List Templates", "GET", "/list-templates",
            ),
            "create_image": VendorOperation(
                "create_image", "Create Image", "POST", "/create?template_id={template_id}",
                ("template_id",), retryable=False, idempotency="non_idempotent",
                description=(
                    "Generate an image from a JPEG/PNG template. template_id is the query "
                    "parameter and body carries the template fields."
                ),
            ),
            "create_pdf": VendorOperation(
                "create_pdf", "Create PDF", "POST", "/create?template_id={template_id}",
                ("template_id",), retryable=False, idempotency="non_idempotent",
                description=(
                    "Generate a PDF from a PDF template. template_id is the query "
                    "parameter and body carries the template fields."
                ),
            ),
        },
    ),
    "autopilot": VendorSpec(
        key="autopilot",
        display_name="Autopilot",
        description="Autopilot contacts, lists, and journeys.",
        category="marketing",
        base_url="https://api2.autopilothq.com/v1",
        auth_kind="header",
        auth_header="autopilotapikey",
        credential_fields=("api_key",),
        operations={
            "upsert_contact": VendorOperation(
                "upsert_contact", "Create or Update Contact", "POST", "/contact", (),
                retryable=False, idempotency="non_idempotent",
                description="Create or update a contact; body is {\"contact\": {...}}.",
            ),
            "get_contact": VendorOperation(
                "get_contact", "Get Contact", "GET", "/contact/{contact_id}", ("contact_id",),
            ),
            "delete_contact": VendorOperation(
                "delete_contact", "Delete Contact", "DELETE", "/contact/{contact_id}", ("contact_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "list_contacts": VendorOperation(
                "list_contacts", "List Contacts", "GET", "/contacts",
                description="List contacts; bookmark pagination goes in payload.params.",
            ),
            "create_list": VendorOperation(
                "create_list", "Create List", "POST", "/list", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "list_lists": VendorOperation("list_lists", "List Lists", "GET", "/lists"),
            "add_contact_to_list": VendorOperation(
                "add_contact_to_list", "Add Contact to List", "POST",
                "/list/{list_id}/contact/{contact_id}", ("list_id", "contact_id"),
                retryable=False, idempotency="non_idempotent",
            ),
            "remove_contact_from_list": VendorOperation(
                "remove_contact_from_list", "Remove Contact from List", "DELETE",
                "/list/{list_id}/contact/{contact_id}", ("list_id", "contact_id"),
                retryable=False, idempotency="non_idempotent",
            ),
            "contact_in_list": VendorOperation(
                "contact_in_list", "Check Contact in List", "GET",
                "/list/{list_id}/contact/{contact_id}", ("list_id", "contact_id"),
            ),
            "list_contacts_in_list": VendorOperation(
                "list_contacts_in_list", "List Contacts in List", "GET",
                "/list/{list_id}/contacts", ("list_id",),
            ),
            "add_contact_to_journey": VendorOperation(
                "add_contact_to_journey", "Add Contact to Journey", "POST",
                "/trigger/{trigger_id}/contact/{contact_id}", ("trigger_id", "contact_id"),
                retryable=False, idempotency="non_idempotent",
            ),
            "list_custom_fields": VendorOperation(
                "list_custom_fields", "List Custom Fields", "GET", "/contacts/custom_fields",
            ),
            "list_triggers": VendorOperation("list_triggers", "List Triggers", "GET", "/triggers"),
        },
    ),
}


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
            "batch": "catalog_conversion_6",
        },
    )


def build_batch6_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Return the batch 6 native connector/definition pairs that can run.

    Unsupported catalog keys are intentionally omitted; see
    :data:`UNSUPPORTED_BATCH6_KEYS` for the per-key reason.
    """
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
