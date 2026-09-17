"""Connector Framework SDK (spec 37+).

Defines the base Connector class, registry, and standard operations
that all external integrations must implement. This replaces ad-hoc
node-specific code with a consistent framework.

ConnectorSDK is the base class for all first-class connectors. Each
connector implements connect(), disconnect(), node_types, and op_execute()
to provide standardized integration with the engine.
"""

from __future__ import annotations

from abc import abstractmethod
from enum import Enum
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.connectors.registry import ConnectorRegistry


# ----------------------------------------------------------------------
# Connector Type Aliases
# ----------------------------------------------------------------------


ConnectorType = str
ConnectorID = str


# ----------------------------------------------------------------------
# Connector Error (spec 37.1)
# ----------------------------------------------------------------------


class ConnectorError(Exception):
    """Base class for connector errors.

    Every error exposes safe information: connector, operation, code,
    safe message, retryable, and retry-after where available. Credentials
    and sensitive provider responses must never be exposed.
    """

    code: str = "CONNECTOR_ERROR"

    def __init__(
        self,
        message: str,
        code: str | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or self.code
        self.retryable = retryable
        self.retry_after = retry_after


# ----------------------------------------------------------------------
# Connector Error Categories (spec 37.6)
# ----------------------------------------------------------------------


class ConnectorErrorCode(str, Enum):
    """Normalized error categories for external provider errors."""

    AUTH_FAILED = "CONNECTOR_AUTH_FAILED"
    RATE_LIMITED = "CONNECTOR_RATE_LIMITED"
    TIMEOUT = "CONNECTOR_TIMEOUT"
    BAD_REQUEST = "CONNECTOR_BAD_REQUEST"
    UNAVAILABLE = "CONNECTOR_UNAVAILABLE"
    NOT_FOUND = "CONNECTOR_NOT_FOUND"
    FORBIDDEN = "CONNECTOR_FORBIDDEN"
    VALIDATION_FAILED = "CONNECTOR_VALIDATION_FAILED"
    NOT_CONFIGURED = "CONNECTOR_NOT_CONFIGURED"


def make_connector_error(
    code: ConnectorErrorCode,
    message: str,
    *,
    retryable: bool = False,
    retry_after: float | None = None,
) -> ConnectorError:
    """Build a typed ConnectorError from an error code.

    Ensures the code and retryable flag are consistent.
    """
    return ConnectorError(
        message=message,
        code=code.value,
        retryable=retryable,
        retry_after=retry_after,
    )


# ----------------------------------------------------------------------
# Connector Definition V1 (spec 37.2)
# ----------------------------------------------------------------------


class ConnectorDefinitionV1(BaseModel):
    """Versioned connector definition (registry metadata)."""

    connector_key: str
    display_name: str
    description: str
    category: str
    connector_version: str
    lifecycle_status: str  # "draft" | "internal" | "beta" | "stable" | "deprecated" | "removed"
    operations: Dict[str, "ConnectorOperationV1"]
    triggers: Dict[str, "ConnectorTriggerV1"]
    credential_types: Dict[str, "CredentialTypeV1"]
    metadata: Dict[str, Any] = {}
    icon: str | None = None


# ----------------------------------------------------------------------
# Connector Operation V1 (spec 37.3)
# ----------------------------------------------------------------------


class ConnectorOperationV1(BaseModel):
    """Definition of a single connector operation."""

    connector_key: str
    connector_version: str
    operation_key: str
    operation_version: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    credential_require: str | None = None  # e.g. "api_key", "bearer", "basic", "oauth2"
    retryable: bool = False
    idempotency: str = "unknown"  # "idempotent" | "conditionally_idempotent" | "non_idempotent" | "unknown"
    node_types: List[str] = []  # node types this operation supports (registry index)


# ----------------------------------------------------------------------
# Connector Trigger V1 (spec 37.4)
# ----------------------------------------------------------------------


class ConnectorTriggerV1(BaseModel):
    """Definition of a single connector trigger."""

    connector_key: str
    connector_version: str
    trigger_key: str
    trigger_version: str
    trigger_type: str  # e.g. "webhook", "scheduled", "polling"
    configuration_schema: dict[str, Any]
    credential_require: str | None = None  # e.g. "api_key", "bearer", "basic", "oauth2"
    node_types: List[str] = []  # node types this trigger supports (registry index)


# ----------------------------------------------------------------------
# Credential Type V1 (spec 37.5)
# ----------------------------------------------------------------------


class CredentialTypeV1(BaseModel):
    """Versioned credential definition.

    Credentials remain server-side; never send secret values to the browser.
    """

    type_key: str  # e.g. "api_key", "bearer", "basic_auth", "oauth2", "api_key_file"
    display_name: str
    description: str
    secret_fields: List[str]  # field names that contain secrets, never logged
    validation_schema: dict[str, Any]  # JSON schema for frontend form; server-side validation
    encryption_required: bool = True


# ----------------------------------------------------------------------
# Connector Lifecycle Enum (spec 30)
# ----------------------------------------------------------------------


class ConnectorLifecycle(str, Enum):
    """Connector lifecycle status."""

    DRAFT = "draft"
    INTERNAL = "internal"
    BETA = "beta"
    STABLE = "stable"
    DEPRECATED = "deprecated"
    REMOVED = "removed"


# ----------------------------------------------------------------------
# Connector Category Enum (spec 37.7)
# ----------------------------------------------------------------------


class ConnectorCategory(str, Enum):
    """Connector category for classification."""

    API = "api"
    WEBHOOK = "webhook"
    SCHEDULE = "schedule"
    TRANSFORM = "transform"
    LOGIC = "logic"


# ----------------------------------------------------------------------
# Universal runtime lifecycle stages (Phase 40)
# ----------------------------------------------------------------------

CONNECTOR_RUNTIME_STAGES = (
    "discover",
    "validate",
    "configure",
    "authenticate",
    "execute",
    "normalize",
    "report",
)


# ----------------------------------------------------------------------
# Connector SDK Base Class (spec 37.1)
# ----------------------------------------------------------------------


class ConnectorSDK:
    """Base class for all first-class connectors.

    Each connector must implement:
    - connect(config): Validate and store configuration
    - disconnect(): Tear down connections
    - node_types: List of node types this connector handles
    - op_execute(operation, payload, context): Execute the connector operation

    The engine routes node execution through ConnectorSDK instances
    when a node type is mapped to a connector key (see executor.py).

    Runtime lifecycle stages (universal contract):
        discover -> validate -> configure -> authenticate ->
        execute -> normalize_output -> report
    """

    def normalize_output(self, operation: str, payload: dict[str, Any], output: Any) -> Any:
        """Lifecycle stage: shape raw provider data once, in the connector.

        Default passthrough; override when the provider wire format needs
        a single normalization point. Called by connector code, not by the
        engine.
        """
        return output

    connector_id: str = ""
    display_name: str = ""
    description: str = ""
    version: str = "1.0.0"
    category: ConnectorCategory | str = ConnectorCategory.API

    def __init__(self, connector_id: str = "", display_name: str = "", description: str = "") -> None:
        self.connector_id = connector_id or self.connector_id
        self.display_name = display_name or self.display_name
        self.description = description or self.description
        self.status: str = "initialized"
        self._metadata: dict[str, Any] = {}

    @property
    def name(self) -> str:
        """Display name alias used by the registry."""
        return self.display_name

    def to_dict(self) -> dict[str, Any]:
        """Serialize connector metadata for API responses."""
        return {
            "connector_id": self.connector_id,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
            "category": self.category.value if isinstance(self.category, ConnectorCategory) else self.category,
            "status": self.status,
            "node_types": self.node_types,
            "metadata": self._metadata,
        }

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Convenience accessor for connector metadata."""
        return self._metadata.get(key, default)

    async def connect(self, config: dict[str, Any]) -> bool:
        """Validate and store the connector configuration.

        Subclasses must override this method to validate and store
        their specific configuration. Returns True on success.
        """
        raise NotImplementedError("Subclasses must implement connect()")

    async def disconnect(self) -> None:
        """Tear down the connector connection."""
        self.status = "disconnected"
        self._metadata.clear()

    @property
    def node_types(self) -> list[str]:
        """Return the node types handled by this connector."""
        return []

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a connector operation.

        Subclasses must override this method to perform the actual
        operation. Returns a dict with the operation result.
        """
        raise NotImplementedError("Subclasses must implement op_execute()")

    async def op_health_check(self) -> "ConnectorHealthCheck":
        """Check connector health. Default: unhealthy unless connected."""
        if self.status != "connected":
            return ConnectorHealthCheck(healthy=False, message="Connector not connected.")
        return ConnectorHealthCheck(healthy=True, message="Connector is operational.")


# ----------------------------------------------------------------------
# Connector Operations Mixin (spec 37.8)
# ----------------------------------------------------------------------


class ConnectorOperations:
    """Mixin that provides default implementations of standard connector
    operations. Subclasses override as needed.

    Used by connector SDK classes to implement the ConnectorOperations
    interface without redefining every method. Always mixed with
    ConnectorSDK, which provides `status` and `_metadata`.
    """

    status: str
    _metadata: dict[str, Any]

    async def connect(self, config: dict[str, Any]) -> bool:
        """Default: not implemented."""
        raise NotImplementedError("Subclasses must implement connect()")

    async def disconnect(self) -> None:
        """Default: clear metadata."""
        self._metadata.clear()

    @property
    def node_types(self) -> list[str]:
        """Default: no node types."""
        return []

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Default: not implemented."""
        raise NotImplementedError("Subclasses must implement op_execute()")

    async def op_health_check(self) -> ConnectorHealthCheck:
        """Default health check: returns unhealthy if not connected."""
        if self.status != "connected":
            return ConnectorHealthCheck(healthy=False, message="Connector not connected.")
        return ConnectorHealthCheck(healthy=True, message="Connector is operational.")

    async def op_search(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default: not implemented."""
        raise NotImplementedError("Subclasses may implement op_search()")

    async def op_get(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default: not implemented."""
        raise NotImplementedError("Subclasses may implement op_get()")

    async def op_create(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default: not implemented."""
        raise NotImplementedError("Subclasses may implement op_create()")

    async def op_update(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default: not implemented."""
        raise NotImplementedError("Subclasses may implement op_update()")

    async def op_delete(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default: not implemented."""
        raise NotImplementedError("Subclasses may implement op_delete()")

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default: not implemented."""
        raise NotImplementedError("Subclasses may implement op_list()")

    async def op_describe(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default: not implemented."""
        raise NotImplementedError("Subclasses may implement op_describe()")


# ----------------------------------------------------------------------
# Connector Health Check (spec 37.9)
# ----------------------------------------------------------------------


class ConnectorHealthCheck(BaseModel):
    """Health check result for a connector.

    Returns healthy=True/False with a safe message (no secrets).
    """

    healthy: bool
    message: str


class ConnectorInfo(BaseModel):
    """Lightweight connector info for registry queries."""

    connector_id: str
    name: str
    description: str
    version: str
    category: str
    status: str
    node_types: list[str]
    metadata: dict[str, Any] = {}


class ConnectorStatus:
    """Status values for connector state."""

    INITIALIZED = "initialized"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


# ----------------------------------------------------------------------
# Standard operation names (convention, not enforcement)
# ----------------------------------------------------------------------


OP_SEARCH = "search"
OP_GET = "get"
OP_CREATE = "create"
OP_UPDATE = "update"
OP_DELETE = "delete"
OP_EXECUTE = "execute"
OP_HEALTH_CHECK = "health_check"
OP_LIST = "list"
OP_DESCRIBE = "describe"


_registry: "ConnectorRegistry | None" = None


def get_registry() -> "ConnectorRegistry":
    """Get the global connector registry singleton.

    The registry is initialized during app startup via the lifespan
    context manager in main.py (or worker startup). This function
    returns the singleton instance so the API layer and other modules
    can register and discover connectors.
    """
    global _registry
    if _registry is None:
        from app.connectors.registry import ConnectorRegistry

        _registry = ConnectorRegistry()
    return _registry


# Export the public API
__all__ = [
    "ConnectorSDK",
    "ConnectorError",
    "ConnectorHealthCheck",
    "ConnectorInfo",
    "ConnectorErrorCode",
    "make_connector_error",
    "ConnectorDefinitionV1",
    "ConnectorOperationV1",
    "ConnectorTriggerV1",
    "CredentialTypeV1",
    "ConnectorCategory",
    "ConnectorLifecycle",
    "ConnectorSDK",
    "OP_SEARCH",
    "OP_GET",
    "OP_CREATE",
    "OP_UPDATE",
    "OP_DELETE",
    "OP_EXECUTE",
    "OP_HEALTH_CHECK",
    "OP_LIST",
    "OP_DESCRIBE",
    "ConnectorStatus",
    "get_registry",
    "register_builtin_connectors",
    "ensure_builtin_connectors",
]


def ensure_builtin_connectors() -> None:
    """Idempotent lazy registration for contexts where app lifespan did
    not run (TestClient without a with-block, ad-hoc scripts, external
    tooling). Cheap once populated."""
    registry = get_registry()
    try:
        populated = bool(registry.list_definitions())
    except Exception:
        populated = False
    if not populated:
        register_builtin_connectors()


def register_builtin_connectors(generated_dir: str | None = None) -> None:
    """Register the built-in connector set on the global registry.

    Called at app startup (main.py lifespan) and by standalone workers
    so connector-only node types resolve everywhere executions run.
    OpenAPI-imported triples are picked up from ``generated_dir``
    (default: app/connectors/generated); a missing dir is fine.
    """
    from app.connectors.airtable_connector import AirtableConnector
    from app.connectors.airtable_definition import build_airtable_definition
    from app.connectors.asana_connector import AsanaConnector
    from app.connectors.asana_definition import build_asana_definition
    from app.connectors.calendly_connector import CalendlyConnector
    from app.connectors.calendly_definition import build_calendly_definition
    from app.connectors.gitlab_connector import GitLabConnector
    from app.connectors.gitlab_definition import build_gitlab_definition
    from app.connectors.bitbucket_connector import BitbucketConnector
    from app.connectors.bitbucket_definition import build_bitbucket_definition
    from app.connectors.whatsapp_connector import WhatsAppConnector
    from app.connectors.whatsapp_definition import build_whatsapp_definition
    from app.connectors.clickup_connector import ClickUpConnector
    from app.connectors.clickup_definition import build_clickup_definition
    from app.connectors.pipedrive_connector import PipedriveConnector
    from app.connectors.pipedrive_definition import build_pipedrive_definition
    from app.connectors.dropbox_connector import DropboxConnector
    from app.connectors.dropbox_definition import build_dropbox_definition
    from app.connectors.openai_connector import OpenAIConnector
    from app.connectors.openai_definition import build_openai_definition
    from app.connectors.twilio_connector import TwilioConnector
    from app.connectors.twilio_definition import build_twilio_definition
    from app.connectors.zoom_connector import ZoomConnector
    from app.connectors.zoom_definition import build_zoom_definition
    from app.connectors.linear_connector import LinearConnector
    from app.connectors.linear_definition import build_linear_definition
    from app.connectors.discord_connector import DiscordConnector
    from app.connectors.discord_definition import build_discord_definition
    from app.connectors.gmail_connector import GmailConnector
    from app.connectors.gmail_definition import build_gmail_definition
    from app.connectors.github_connector import GitHubConnector
    from app.connectors.github_definition import build_github_definition
    from app.connectors.google_calendar_connector import GoogleCalendarConnector
    from app.connectors.google_calendar_definition import build_google_calendar_definition
    from app.connectors.google_drive_connector import GoogleDriveConnector
    from app.connectors.google_drive_definition import build_google_drive_definition
    from app.connectors.google_sheets_connector import GoogleSheetsConnector
    from app.connectors.google_sheets_definition import build_google_sheets_definition
    from app.connectors.hubspot_connector import HubSpotConnector
    from app.connectors.hubspot_definition import build_hubspot_definition
    from app.connectors.http_connector import HTTPConnector
    from app.connectors.jira_connector import JiraConnector
    from app.connectors.jira_definition import build_jira_definition
    from app.connectors.mongodb_connector import MongoDBConnector
    from app.connectors.mongodb_definition import build_mongodb_definition
    from app.connectors.msteams_connector import MSTeamsConnector
    from app.connectors.msteams_definition import build_msteams_definition
    from app.connectors.mysql_connector import MySQLConnector
    from app.connectors.mysql_definition import build_mysql_definition
    from app.connectors.notion_connector import NotionConnector
    from app.connectors.notion_definition import build_notion_definition
    from app.connectors.outlook_connector import OutlookConnector
    from app.connectors.outlook_definition import build_outlook_definition
    from app.connectors.postgres_connector import PostgresConnector
    from app.connectors.postgres_definition import build_postgres_definition
    from app.connectors.redis_connector import RedisConnector
    from app.connectors.redis_definition import build_redis_definition
    from app.connectors.salesforce_connector import SalesforceConnector
    from app.connectors.salesforce_definition import build_salesforce_definition
    from app.connectors.schedule_connector import ScheduleConnector
    from app.connectors.shopify_connector import ShopifyConnector
    from app.connectors.shopify_definition import build_shopify_definition
    from app.connectors.slack_connector import SlackConnector
    from app.connectors.slack_definition import build_slack_definition
    from app.connectors.stripe_connector import StripeConnector
    from app.connectors.stripe_definition import build_stripe_definition
    from app.connectors.trello_connector import TrelloConnector
    from app.connectors.trello_definition import build_trello_definition
    from app.connectors.webhook_connector import WebhookConnector

    # connector_id -> (instance factory, definition builder). Definition
    # builders are paired with their connectors so discovery, the node
    # catalog and execution always agree on operations/schemas.
    builtins: list[tuple[ConnectorSDK, Any]] = [
        (HTTPConnector(), None),
        (SalesforceConnector(), build_salesforce_definition),
        (HubSpotConnector(), build_hubspot_definition),
        (GoogleCalendarConnector(), build_google_calendar_definition),
        (GoogleSheetsConnector(), build_google_sheets_definition),
        (GmailConnector(), build_gmail_definition),
        (ScheduleConnector(), None),
        (WebhookConnector(), None),
        # Phase 11 business connectors
        (PostgresConnector(), build_postgres_definition),
        (MySQLConnector(), build_mysql_definition),
        (GoogleDriveConnector(), build_google_drive_definition),
        (SlackConnector(), build_slack_definition),
        (MSTeamsConnector(), build_msteams_definition),
        (OutlookConnector(), build_outlook_definition),
        (GitHubConnector(), build_github_definition),
        (NotionConnector(), build_notion_definition),
        (JiraConnector(), build_jira_definition),
        (DiscordConnector(), build_discord_definition),
        (StripeConnector(), build_stripe_definition),
        (MongoDBConnector(), build_mongodb_definition),
        (RedisConnector(), build_redis_definition),
        (AirtableConnector(), build_airtable_definition),
        (ShopifyConnector(), build_shopify_definition),
        (TrelloConnector(), build_trello_definition),
        (AsanaConnector(), build_asana_definition),
        (LinearConnector(), build_linear_definition),
        (CalendlyConnector(), build_calendly_definition),
        (GitLabConnector(), build_gitlab_definition),
        (ZoomConnector(), build_zoom_definition),
        (TwilioConnector(), build_twilio_definition),
        (BitbucketConnector(), build_bitbucket_definition),
        (WhatsAppConnector(), build_whatsapp_definition),
        (ClickUpConnector(), build_clickup_definition),
        (PipedriveConnector(), build_pipedrive_definition),
        (DropboxConnector(), build_dropbox_definition),
        (OpenAIConnector(), build_openai_definition),
    ]

    registry = get_registry()
    registry.initialize()
    for instance, definition_builder in builtins:
        if definition_builder is not None:
            defn = definition_builder()
        else:
            category = instance.category.value if isinstance(instance.category, ConnectorCategory) else instance.category
            defn = ConnectorDefinitionV1(
                connector_key=instance.connector_id,
                display_name=instance.display_name,
                description=instance.description,
                category=category,
                connector_version=instance.version,
                lifecycle_status=ConnectorLifecycle.STABLE.value,
                operations=_builtin_operations(instance.connector_id, instance.version),
                triggers=_builtin_triggers(instance.connector_id, instance.version),
                credential_types=_builtin_credential_types(instance.connector_id),
            )
        registry.register(instance, defn)

    # OpenAPI-imported connectors (Phase 1): optional on-disk triples in
    # app/connectors/generated/. Missing dir or broken files are skipped
    # silently — builtins above are never affected.
    try:
        from pathlib import Path as _Path

        from app.connectors.openapi_emit import register_generated as _register_generated

        _generated_dir = _Path(generated_dir) if generated_dir else _Path(__file__).resolve().parent / "generated"
        if _generated_dir.is_dir():
            _count = _register_generated(registry, str(_generated_dir))
            if _count:
                logging.getLogger("connectors").info("registered %d generated connectors", _count)
    except Exception:
        logging.getLogger("connectors").exception("generated connector scan failed")


def _builtin_operations(connector_key: str, connector_version: str) -> Dict[str, ConnectorOperationV1]:
    """Populated operation definitions so discovery returns real data."""
    ops: Dict[str, ConnectorOperationV1] = {}
    if connector_key in ("http", "salesforce"):
        # (key, display, description, retryable, idempotency) — spec 35
        for op_key, display, desc, retryable, idem in (
            ("query", "Query", "Run a query.", True, "idempotent"),
            ("get", "Get", "Fetch a single record.", False, "idempotent"),
            ("create", "Create", "Create a record.", False, "non_idempotent"),
            ("update", "Update", "Update a record.", True, "idempotent"),
            ("delete", "Delete", "Delete a record.", True, "idempotent"),
            ("list", "List", "List resources.", True, "idempotent"),
            ("describe", "Describe", "Describe a resource.", True, "idempotent"),
            ("execute", "Execute", "Generic execute operation.", True, "non_idempotent"),
        ):
            ops[op_key] = ConnectorOperationV1(
                connector_key=connector_key,
                connector_version=connector_version,
                operation_key=op_key,
                operation_version="1.0.0",
                display_name=display,
                description=desc,
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object", "properties": {}},
                credential_require="salesforce" if connector_key == "salesforce" else "http",
                retryable=retryable,
                idempotency=idem,
            )
    return ops


def _builtin_triggers(connector_key: str, connector_version: str) -> Dict[str, ConnectorTriggerV1]:
    triggers: Dict[str, ConnectorTriggerV1] = {}
    if connector_key == "schedule":
        triggers["cron"] = ConnectorTriggerV1(
            connector_key="schedule",
            connector_version=connector_version,
            trigger_key="cron",
            trigger_version="1.0.0",
            trigger_type="scheduled",
            configuration_schema={"type": "object", "properties": {"cron": {"type": "string"}}},
            credential_require=None,
        )
    if connector_key == "webhook":
        triggers["receive"] = ConnectorTriggerV1(
            connector_key="webhook",
            connector_version=connector_version,
            trigger_key="receive",
            trigger_version="1.0.0",
            trigger_type="webhook",
            configuration_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            credential_require=None,
        )
    return triggers


def _builtin_credential_types(connector_key: str) -> Dict[str, CredentialTypeV1]:
    if connector_key == "salesforce":
        return {
            "salesforce": CredentialTypeV1(
                type_key="salesforce",
                display_name="Salesforce",
                description="Salesforce org connection (OAuth2 password grant).",
                secret_fields=["client_secret", "password"],
                validation_schema={"type": "object"},
                encryption_required=True,
            )
        }
    if connector_key == "http":
        return {
            "http": CredentialTypeV1(
                type_key="http",
                display_name="HTTP",
                description="API credentials injectable into HTTP Request headers.",
                secret_fields=["api_key", "password"],
                validation_schema={"type": "object"},
                encryption_required=True,
            )
        }
    return {}