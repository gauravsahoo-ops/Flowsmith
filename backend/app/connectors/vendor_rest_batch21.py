"""Native REST connectors for catalog conversion batch 21.

Each implemented connector uses a fixed vendor host, the authentication
contract declared by the matching n8n credential, and operation paths taken
from the corresponding n8n node implementation. Catalog keys whose n8n node
requires request signing, a token/session exchange, or form-encoded
credentials are listed in :data:`UNSUPPORTED_BATCH21_KEYS` with the specific
reason instead of being given invented endpoints.
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


BATCH21_CATALOG_KEYS = frozenset({
    "u_proc",
    "unleashed_software",
    "uplead",
    "uptime_robot",
    "url_scan_io",
    "venafi_tls_protect_cloud",
    "venafi_tls_protect_datacenter",
    "vero",
    "vonage",
    "wekan",
})

# Short alias kept alongside the descriptive name used by newer batches.
BATCH21_KEYS = BATCH21_CATALOG_KEYS


VENDOR_SPECS: dict[str, VendorSpec] = {
    "u_proc": VendorSpec(
        key="u_proc",
        display_name="uProc",
        description="uProc data enrichment and processing tools.",
        category="analytics",
        base_url="https://api.uproc.io/api/v2",
        auth_kind="basic",
        basic_user_field="email",
        basic_password_field="api_key",
        credential_fields=("email", "api_key"),
        operations={
            "get_profile": VendorOperation(
                "get_profile", "Get Profile", "GET", "/profile",
            ),
            "process": VendorOperation(
                "process", "Process", "POST", "/process", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Run a uProc processor. The body accepts processor, params, "
                    "and an optional callback matching the vendor API."
                ),
            ),
        },
    ),
    "uplead": VendorSpec(
        key="uplead",
        display_name="Uplead",
        description="Uplead company and person enrichment.",
        category="crm",
        base_url="https://api.uplead.com/v2",
        auth_kind="header",
        auth_header="Authorization",
        credential_fields=("api_key",),
        operations={
            "search_company": VendorOperation(
                "search_company", "Search Company", "GET", "/company-search",
                description=(
                    "Look up a company by domain or company name; pass domain "
                    "and company as query parameters."
                ),
            ),
            "search_person": VendorOperation(
                "search_person", "Search Person", "GET", "/person-search",
                description=(
                    "Look up a person by email or by domain plus first and last "
                    "name; pass email, first_name, last_name, and domain as query "
                    "parameters."
                ),
            ),
        },
    ),
    "url_scan_io": VendorSpec(
        key="url_scan_io",
        display_name="urlscan.io",
        description="urlscan.io website scans and scan search.",
        category="developer",
        base_url="https://urlscan.io/api/v1",
        auth_kind="header",
        auth_header="API-KEY",
        credential_fields=("api_key",),
        operations={
            "get_scan": VendorOperation(
                "get_scan", "Get Scan", "GET", "/result/{scan_id}", ("scan_id",),
            ),
            "search_scans": VendorOperation(
                "search_scans", "Search Scans", "GET", "/search",
                description=(
                    "Search scans; pass q, size, and search_after as query "
                    "parameters."
                ),
            ),
            "perform_scan": VendorOperation(
                "perform_scan", "Perform Scan", "POST", "/scan", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Submit a URL for scanning. The body accepts url, visibility, "
                    "tags, customAgent, referer, and overrideSafety."
                ),
            ),
        },
    ),
    "venafi_tls_protect_cloud": VendorSpec(
        key="venafi_tls_protect_cloud",
        display_name="Venafi TLS Protect Cloud",
        description=(
            "Venafi TLS Protect Cloud certificate requests and certificates. "
            "The region value must be 'cloud' for the US service or 'eu' for "
            "the European service."
        ),
        category="developer",
        base_url="https://api.venafi.{region}",
        auth_kind="header",
        auth_header="tppl-api-key",
        credential_fields=("api_key",),
        extra_required=("region",),
        operations={
            "create_certificate_request": VendorOperation(
                "create_certificate_request", "Create Certificate Request", "POST",
                "/outagedetection/v1/certificaterequests", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Create a certificate request. The body accepts "
                    "applicationId, certificateIssuingTemplateId, isVaaSGenerated, "
                    "csrAttributes, and certificateSigningRequest matching the "
                    "vendor API."
                ),
            ),
            "get_certificate_request": VendorOperation(
                "get_certificate_request", "Get Certificate Request", "GET",
                "/outagedetection/v1/certificaterequests/{certificate_request_id}",
                ("certificate_request_id",),
            ),
            "list_certificate_requests": VendorOperation(
                "list_certificate_requests", "List Certificate Requests", "GET",
                "/outagedetection/v1/certificaterequests",
                description=(
                    "List certificate requests; pass vendor filters such as limit "
                    "as query parameters."
                ),
            ),
            "delete_certificate": VendorOperation(
                "delete_certificate", "Delete Certificate", "POST",
                "/outagedetection/v1/certificates/deletion", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Retire certificates. The body accepts certificateIds as an "
                    "array of certificate identifiers."
                ),
            ),
            "get_certificate": VendorOperation(
                "get_certificate", "Get Certificate", "GET",
                "/outagedetection/v1/certificates/{certificate_id}",
                ("certificate_id",),
            ),
            "list_certificates": VendorOperation(
                "list_certificates", "List Certificates", "GET",
                "/outagedetection/v1/certificates",
                description=(
                    "List certificates; pass vendor filters such as limit as "
                    "query parameters."
                ),
            ),
            "renew_certificate": VendorOperation(
                "renew_certificate", "Renew Certificate", "POST",
                "/outagedetection/v1/certificaterequests", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Renew an existing certificate. The body accepts "
                    "certificateSigningRequest, certificateIssuingTemplateId, "
                    "applicationId, and existingCertificateId."
                ),
            ),
        },
    ),
}


# Keys intentionally left out of build_batch21_connectors(). Keeping the
# reasons next to the spec table makes each gap explicit instead of publishing
# a connector whose operations cannot authenticate with the shared
# VendorRESTConnector implementation.
UNSUPPORTED_BATCH21_KEYS: dict[str, str] = {
    "unleashed_software": (
        "Unleashed Software signs every request with HMAC-SHA256 over the query "
        "string using the API key, then sends the result in the "
        "api-auth-signature header together with api-auth-id. VendorRESTConnector "
        "supports only static bearer, basic, header, and query credentials and "
        "cannot compute per-request signatures."
    ),
    "uptime_robot": (
        "UptimeRobot authenticates by adding the API key as the api_key field of "
        "an application/x-www-form-urlencoded request body on every call. "
        "VendorRESTConnector sends JSON bodies only and never injects credentials "
        "into a form body, so its requests would be unauthenticated."
    ),
    "venafi_tls_protect_datacenter": (
        "Venafi TLS Protect Datacenter pre-authenticates by exchanging a client "
        "ID, username, and password for an expiring access token at "
        "POST {domain}/vedauth/authorize/oauth, then sends that token as a bearer "
        "credential. VendorRESTConnector has no pre-authentication or OAuth "
        "password-grant token exchange support."
    ),
    "vero": (
        "Vero authenticates by adding the auth_token field to an "
        "application/x-www-form-urlencoded request body on every call. "
        "VendorRESTConnector sends JSON bodies only and never injects credentials "
        "into a form body, so its requests would be unauthenticated."
    ),
    "vonage": (
        "The n8n Vonage node posts to the legacy SMS API with api_key and "
        "api_secret injected as application/x-www-form-urlencoded fields on every "
        "request. VendorRESTConnector sends JSON bodies only and never injects "
        "credentials into a form body, so its requests would be unauthenticated."
    ),
    "wekan": (
        "Wekan pre-authenticates by posting the username and password to "
        "{url}/users/login and then sends the returned session token in an "
        "Authorization bearer header. VendorRESTConnector has no session login or "
        "token-refresh support, so it cannot obtain the token Wekan requires."
    ),
}


def _build_definition(spec: VendorSpec) -> ConnectorDefinitionV1:
    operations = {
        key: ConnectorOperationV1(
            connector_key=spec.key,
            connector_version="1.0.0",
            operation_key=key,
            operation_version="1.0.0",
            display_name=op.display_name,
            description=op.description or f"{op.display_name} for {spec.display_name}.",
            input_schema={
                "type": "object",
                "properties": {
                    "params": {"type": "object"},
                    "body": {"type": "object"},
                },
                "required": list(op.requires),
            },
            output_schema={"type": "object"},
            credential_require=spec.key,
            retryable=op.retryable,
            idempotency=op.idempotency,
            node_types=[spec.key],
        )
        for key, op in spec.operations.items()
    }
    credential_properties: dict[str, Any] = {
        field: {"type": "string", "title": field.replace("_", " ").title()}
        for field in spec.credential_fields
    }
    return ConnectorDefinitionV1(
        connector_key=spec.key,
        display_name=spec.display_name,
        description=spec.description,
        category=spec.category,
        connector_version="1.0.0",
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=operations,
        triggers={},
        credential_types={
            spec.key: CredentialTypeV1(
                type_key=spec.key,
                display_name=f"{spec.display_name} Credentials",
                description=f"Credentials for {spec.display_name}.",
                secret_fields=list(spec.credential_fields),
                validation_schema={"type": "object", "properties": credential_properties},
                encryption_required=True,
            )
        },
        metadata={
            "implementation": "native",
            "batch": "catalog_conversion_21",
        },
    )


def build_batch21_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 21 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
