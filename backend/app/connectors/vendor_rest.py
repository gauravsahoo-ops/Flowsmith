"""Native REST connector family for the first catalog conversion batch.

These are vendor-specific connectors with fixed hosts, auth handling, and
operation maps. They are intentionally small first-class connectors, not
catalog-only adapters that accept an arbitrary endpoint_url.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorError,
    ConnectorErrorCode,
    ConnectorLifecycle,
    ConnectorOperationV1,
    ConnectorSDK,
    CredentialTypeV1,
    make_connector_error,
)


@dataclass(frozen=True)
class VendorOperation:
    key: str
    display_name: str
    method: str
    path: str
    requires: tuple[str, ...] = ()
    retryable: bool = True
    idempotency: str = "idempotent"
    description: str = ""


@dataclass(frozen=True)
class VendorSpec:
    key: str
    display_name: str
    description: str
    category: str
    base_url: str
    auth_kind: str  # bearer | basic | header
    credential_fields: tuple[str, ...]
    operations: dict[str, VendorOperation]
    auth_header: str = ""
    basic_user_field: str = ""
    basic_password_field: str = ""
    default_password: str = ""
    extra_required: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


VENDOR_SPECS: dict[str, VendorSpec] = {
    "action_network": VendorSpec(
        key="action_network",
        display_name="Action Network",
        description="Action Network people, events, and advocacy actions.",
        category="crm",
        base_url="https://actionnetwork.org/api/v2",
        auth_kind="header",
        auth_header="OSDI-API-Token",
        credential_fields=("api_key",),
        operations={
            "list_people": VendorOperation("list_people", "List People", "GET", "/people"),
            "get_person": VendorOperation("get_person", "Get Person", "GET", "/people/{person_id}", ("person_id",)),
            "create_person": VendorOperation(
                "create_person", "Create Person", "POST", "/people", (),
                retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "bamboo_hr": VendorSpec(
        key="bamboo_hr",
        display_name="BambooHR",
        description="BambooHR employee directory and records.",
        category="productivity",
        base_url="https://api.bamboohr.com/api/groups/{company_domain}/v1",
        auth_kind="basic",
        basic_user_field="api_key",
        default_password="x",
        credential_fields=("api_key",),
        extra_required=("company_domain",),
        operations={
            "list_employees": VendorOperation("list_employees", "List Employees", "GET", "/employees/directory"),
            "get_employee": VendorOperation("get_employee", "Get Employee", "GET", "/employees/{employee_id}", ("employee_id",)),
            "create_employee": VendorOperation(
                "create_employee", "Create Employee", "POST", "/employees", (),
                retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "chargebee": VendorSpec(
        key="chargebee",
        display_name="Chargebee",
        description="Chargebee customers and subscription billing records.",
        category="finance",
        base_url="https://{site}.chargebee.com/api/v2",
        auth_kind="basic",
        basic_user_field="api_key",
        default_password="x",
        credential_fields=("api_key",),
        extra_required=("site",),
        operations={
            "list_customers": VendorOperation("list_customers", "List Customers", "GET", "/customers"),
            "get_customer": VendorOperation("get_customer", "Get Customer", "GET", "/customers/{customer_id}", ("customer_id",)),
            "create_customer": VendorOperation(
                "create_customer", "Create Customer", "POST", "/customers", (),
                retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "circle_ci": VendorSpec(
        key="circle_ci",
        display_name="CircleCI",
        description="CircleCI users, projects, pipelines, and workflows.",
        category="developer",
        base_url="https://circleci.com/api/v2",
        auth_kind="header",
        auth_header="Circle-Token",
        credential_fields=("api_key",),
        operations={
            "get_user": VendorOperation("get_user", "Get Current User", "GET", "/me"),
            "list_pipelines": VendorOperation(
                "list_pipelines", "List Pipelines", "GET",
                "/project/{project_slug}/pipeline", ("project_slug",),
            ),
            "get_workflow": VendorOperation(
                "get_workflow", "Get Workflow", "GET", "/workflow/{workflow_id}", ("workflow_id",),
            ),
        },
    ),
    "confluence": VendorSpec(
        key="confluence",
        display_name="Confluence",
        description="Atlassian Confluence pages and content.",
        category="productivity",
        base_url="https://{site}.atlassian.net/wiki/rest/api",
        auth_kind="basic",
        basic_user_field="email",
        basic_password_field="api_token",
        credential_fields=("email", "api_token"),
        extra_required=("site",),
        operations={
            "list_pages": VendorOperation(
                "list_pages", "List Pages", "GET", "/content",
                description="List Confluence content; pass query params through payload.params.",
            ),
            "get_page": VendorOperation("get_page", "Get Page", "GET", "/content/{page_id}", ("page_id",)),
        },
    ),
    "contentful": VendorSpec(
        key="contentful",
        display_name="Contentful",
        description="Contentful Management API entries and content types.",
        category="productivity",
        base_url="https://api.contentful.com",
        auth_kind="bearer",
        credential_fields=("access_token",),
        extra_required=("space_id", "environment_id"),
        operations={
            "list_entries": VendorOperation(
                "list_entries", "List Entries", "GET",
                "/spaces/{space_id}/environments/{environment_id}/entries",
                ("space_id", "environment_id"),
            ),
            "get_entry": VendorOperation(
                "get_entry", "Get Entry", "GET",
                "/spaces/{space_id}/environments/{environment_id}/entries/{entry_id}",
                ("space_id", "environment_id", "entry_id"),
            ),
            "create_entry": VendorOperation(
                "create_entry", "Create Entry", "POST",
                "/spaces/{space_id}/environments/{environment_id}/entries",
                ("space_id", "environment_id"), retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "customer_io": VendorSpec(
        key="customer_io",
        display_name="Customer.io",
        description="Customer.io customers and messaging profiles.",
        category="communication",
        base_url="https://api.customer.io/v1",
        auth_kind="bearer",
        credential_fields=("api_key",),
        operations={
            "list_customers": VendorOperation("list_customers", "List Customers", "GET", "/customers"),
            "get_customer": VendorOperation("get_customer", "Get Customer", "GET", "/customers/{customer_id}", ("customer_id",)),
        },
    ),
    "databricks": VendorSpec(
        key="databricks",
        display_name="Databricks",
        description="Databricks clusters and workspace resources.",
        category="database",
        base_url="https://{workspace}.cloud.databricks.com/api/2.0",
        auth_kind="bearer",
        credential_fields=("access_token",),
        extra_required=("workspace",),
        operations={
            "list_clusters": VendorOperation("list_clusters", "List Clusters", "GET", "/clusters/list"),
            "get_cluster": VendorOperation("get_cluster", "Get Cluster", "GET", "/clusters/get", ("cluster_id",)),
        },
    ),
    "freshservice": VendorSpec(
        key="freshservice",
        display_name="Freshservice",
        description="Freshservice service-desk tickets and requests.",
        category="productivity",
        base_url="https://{domain}.freshservice.com/api/v2",
        auth_kind="basic",
        basic_user_field="api_key",
        default_password="x",
        credential_fields=("api_key",),
        extra_required=("domain",),
        operations={
            "list_tickets": VendorOperation("list_tickets", "List Tickets", "GET", "/tickets"),
            "get_ticket": VendorOperation("get_ticket", "Get Ticket", "GET", "/tickets/{ticket_id}", ("ticket_id",)),
            "create_ticket": VendorOperation(
                "create_ticket", "Create Ticket", "POST", "/tickets", (),
                retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "bitly": VendorSpec(
        key="bitly",
        display_name="Bitly",
        description="Bitly short links and analytics.",
        category="communication",
        base_url="https://api-ssl.bitly.com/v4",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "get_bitlink": VendorOperation("get_bitlink", "Get Bitlink", "GET", "/bitlinks/{bitlink}", ("bitlink",)),
            "shorten": VendorOperation(
                "shorten", "Shorten Link", "POST", "/shorten", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "get_clicks": VendorOperation(
                "get_clicks", "Get Clicks", "GET", "/bitlinks/{bitlink}/clicks",
                ("bitlink",),
            ),
        },
    ),
}


class VendorRESTParams(BaseModel):
    operation: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)


class VendorRESTConnector(ConnectorSDK):
    """Small native connector with fixed vendor host and auth contract."""

    implementation_kind = "native"

    def __init__(self, spec: VendorSpec) -> None:
        self.spec = spec
        super().__init__(spec.key, spec.display_name, spec.description)
        self.version = "1.0.0"
        self.category = spec.category

    @property
    def node_types(self) -> list[str]:
        return [self.spec.key]

    async def connect(self, config: dict[str, Any]) -> bool:
        self.status = "connected" if any(config.get(k) for k in self.spec.credential_fields) else "initialized"
        return self.status == "connected"

    async def disconnect(self) -> None:
        self.status = "disconnected"
        self._metadata.clear()

    def _value(self, payload: dict[str, Any], creds: dict[str, Any], name: str) -> Any:
        value = payload.get(name)
        if value is None:
            value = creds.get(name)
        return value

    def _format(self, template: str, payload: dict[str, Any], creds: dict[str, Any]) -> str:
        values = {**creds, **payload}
        missing = [name for name in self.spec.extra_required if not values.get(name)]
        missing += [
            name for name in template.split("{")[1:]
            if not values.get(name.split("}", 1)[0])
        ]
        if missing:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"{self.display_name} requires: {', '.join(sorted(set(missing)))}.",
                retryable=False,
            )
        try:
            return template.format(**values)
        except KeyError as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"{self.display_name} missing path field: {exc.args[0]}.",
                retryable=False,
            ) from exc

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = VendorRESTParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid {self.display_name} payload: {exc}",
                retryable=False,
            ) from exc
        op_key = (operation or params.operation or "").lower()
        op = self.spec.operations.get(op_key)
        if op is None:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"{self.display_name} operation '{op_key}' is not supported.",
                retryable=False,
            )
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get(self.spec.key) or {}

        path = self._format(op.path, params.params, creds)
        base = self._format(self.spec.base_url, params.params, creds).rstrip("/")
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.spec.auth_kind == "bearer":
            token = str(creds.get("access_token") or creds.get("api_key") or "").strip()
            if not token:
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED,
                    f"{self.display_name} requires an access token.",
                    retryable=False,
                )
            headers["Authorization"] = f"Bearer {token}"
        elif self.spec.auth_kind == "header":
            token = str(creds.get("api_key") or creds.get("access_token") or "").strip()
            if not token:
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED,
                    f"{self.display_name} requires an API key.",
                    retryable=False,
                )
            headers[self.spec.auth_header] = token
        elif self.spec.auth_kind == "basic":
            username = str(creds.get(self.spec.basic_user_field) or creds.get("api_key") or "").strip()
            password = str(
                creds.get(self.spec.basic_password_field) or self.spec.default_password or ""
            )
            if not username:
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED,
                    f"{self.display_name} requires a username/API key.",
                    retryable=False,
                )
            headers["Authorization"] = "Basic " + base64.b64encode(
                f"{username}:{password}".encode()
            ).decode()

        body = params.body
        if op.method in {"POST", "PUT", "PATCH"}:
            headers["Content-Type"] = "application/json"
            body = body if body is not None else params.params
        try:
            from app.security.safe_http_client import get_safe_http_client

            client = get_safe_http_client()
            response = await client.request(
                op.method,
                f"{base}{path}",
                headers=headers,
                params=params.params if op.method == "GET" and params.params else None,
                json=body if op.method in {"POST", "PUT", "PATCH"} else None,
                timeout=params.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise make_connector_error(
                ConnectorErrorCode.TIMEOUT,
                f"{self.display_name} request timed out.",
                retryable=True,
            ) from exc
        except ConnectorError:
            raise
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"{self.display_name} request failed: {exc}",
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            code = (
                ConnectorErrorCode.AUTH_FAILED if response.status_code in (401, 403)
                else ConnectorErrorCode.NOT_FOUND if response.status_code == 404
                else ConnectorErrorCode.RATE_LIMITED if response.status_code == 429
                else ConnectorErrorCode.UNAVAILABLE if response.status_code >= 500
                else ConnectorErrorCode.BAD_REQUEST
            )
            raise make_connector_error(
                code,
                f"{self.display_name} returned HTTP {response.status_code}: {response.text[:200]}",
                retryable=response.status_code in (429, 500, 502, 503, 504),
            )
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            data = {"text": response.text}
        return {
            "success": True,
            "connector": self.spec.key,
            "operation": op.key,
            "status_code": response.status_code,
            "data": data,
        }


def build_vendor_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    out: list[tuple[VendorRESTConnector, ConnectorDefinitionV1]] = []
    for spec in VENDOR_SPECS.values():
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
        credential_properties = {
            field: {"type": "string", "title": field.replace("_", " ").title()}
            for field in spec.credential_fields
        }
        definition = ConnectorDefinitionV1(
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
            metadata={"implementation": "native", "batch": "catalog_conversion_1"},
        )
        out.append((VendorRESTConnector(spec), definition))
    return out
