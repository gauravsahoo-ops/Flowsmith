"""HubSpot connector implementing the ConnectorSDK interface.

The Operation layer: maps connector operations (search, get, create,
update) onto the HubSpotProviderClient (Phase 33), which owns all
HubSpot HTTP concerns — OAuth refresh handling, request construction,
response parsing and error translation.

Layering:

    HubSpot Operation (this connector, op_execute)
        -> HubSpotProviderClient (app.providers.hubspot)
            -> SafeHTTPClient (SSRF-protected, redacted logging)
                -> HubSpot CRM v3 API

The engine routes 'hubspot' node types to this connector; credentials
arrive via the CredentialResolver in context["credentials"]["hubspot"].
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorSDK,
    ConnectorError,
    ConnectorCategory,
    ConnectorStatus,
    ConnectorErrorCode,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations
from app.providers.hubspot import STANDARD_OBJECTS, HubSpotProviderClient

logger = logging.getLogger(__name__)


class HubSpotConnectorParams(BaseModel):
    """Parameters for a HubSpot connector operation."""

    operation: str = Field(
        default="search",
        description="Operation to run: search, get, create, update.",
    )
    object_type: str = Field(default="contacts", description="Standard object: contacts, companies, deals, tickets...")
    record_id: str = Field(default="", description="Record id (operation=get/update).")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Property map for the record (operation=create/update).",
    )
    search_field: str = Field(default="email", description="Property to search on (operation=search).")
    search_value: str = Field(default="", description="Value to search for (operation=search).")
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class HubSpotConnector(ConnectorSDK, ConnectorOperations):
    """HubSpot connector - first-class integration for the HubSpot CRM v3 API."""

    connector_id = "hubspot"
    display_name = "HubSpot"
    description = "Search and manage contacts, companies, deals and tickets in HubSpot."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = HubSpotProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["hubspot"]

    # ------------------------------------------------------------------
    # ConnectorSDK interface
    # ------------------------------------------------------------------

    async def connect(self, config: dict[str, Any]) -> bool:
        if not ("private_token" in config or "refresh_token" in config or config.get("oauth")):
            return False
        self.status = ConnectorStatus.CONNECTED
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._provider.reset()
        self._metadata.clear()

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = HubSpotConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid HubSpot payload: {exc}",
                retryable=False,
            ) from exc

        creds = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("hubspot") or {}

        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        try:
            if op == "search":
                return await self._op_search(creds, params, payload)
            if op == "get":
                return await self._op_get(creds, params, payload)
            if op == "create":
                return await self._op_create(creds, params, payload)
            if op == "update":
                return await self._op_update(creds, params, payload)
        except ConnectorError:
            raise

        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST,
            f"Unsupported HubSpot operation '{operation}'.",
            retryable=False,
        )

    @staticmethod
    def _raw(payload: dict[str, Any], key: str) -> Any:
        return (payload or {}).get(key)

    def _require(self, raw_value: Any, message: str) -> str:
        value = str(raw_value or "").strip()
        if not value:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, message, retryable=False)
        return value

    async def _op_search(self, creds: dict[str, Any], params: HubSpotConnectorParams, payload: dict[str, Any]) -> dict[str, Any]:
        ot = str(self._raw(payload, "object_type") or params.object_type)
        field_ = str(self._raw(payload, "search_field") or params.search_field)
        value = self._require(self._raw(payload, "search_value"), "operation=search requires a non-empty search value.")
        return await self._provider.search_records(creds, ot, field_, value, timeout=params.timeout_seconds)

    async def _op_get(self, creds: dict[str, Any], params: HubSpotConnectorParams, payload: dict[str, Any]) -> dict[str, Any]:
        ot = str(self._raw(payload, "object_type") or params.object_type)
        rid = self._require(self._raw(payload, "record_id"), "operation=get requires record_id.")
        return await self._provider.get_record(creds, ot, rid, timeout=params.timeout_seconds)

    async def _op_create(self, creds: dict[str, Any], params: HubSpotConnectorParams, payload: dict[str, Any]) -> dict[str, Any]:
        props = self._raw(payload, "properties") or params.properties
        if not isinstance(props, dict) or not props:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, "operation=create requires a properties map.", retryable=False,
            )
        ot = str(self._raw(payload, "object_type") or params.object_type)
        return await self._provider.create_record(creds, ot, props, timeout=params.timeout_seconds)

    async def _op_update(self, creds: dict[str, Any], params: HubSpotConnectorParams, payload: dict[str, Any]) -> dict[str, Any]:
        props = self._raw(payload, "properties") or params.properties
        if not isinstance(props, dict) or not props:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, "operation=update requires a properties map.", retryable=False,
            )
        ot = str(self._raw(payload, "object_type") or params.object_type)
        rid = self._require(self._raw(payload, "record_id"), "operation=update requires record_id.")
        return await self._provider.update_record(creds, ot, rid, props, timeout=params.timeout_seconds)

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "output": {
                "connector_id": self.connector_id,
                "name": self.name,
                "status": self.status,
                "metadata": self._metadata,
            },
            "success": True,
        }

    async def op_describe(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": self.to_dict(), "success": True}


# Re-exported for definition/discovery parity checks.
HUBSPOT_OBJECTS = STANDARD_OBJECTS
