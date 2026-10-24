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
        description=(
            "Operation to run: search, list, get, create, update, delete, "
            "get_properties, associate_records, get_owner, list_pipelines."
        ),
    )
    object_type: str = Field(default="contacts", description="Standard object: contacts, companies, deals, tickets...")
    owner_id: str = Field(default="", description="HubSpot owner id (operation=get_owner).")
    record_id: str = Field(default="", description="Record id (operation=get/update/delete).")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Property map for the record (operation=create/update).",
    )
    search_field: str = Field(default="email", description="Property to search on (operation=search).")
    search_value: str = Field(default="", description="Value to search for (operation=search).")

    # Associations (operation=associate_records)
    from_object_type: str = Field(default="contacts", description="Source object type.")
    from_record_id: str = Field(default="", description="Source record id.")
    to_object_type: str = Field(default="companies", description="Target object type.")
    to_record_id: str = Field(default="", description="Target record id.")
    association_type_id: str = Field(default="1", description="Association type id / label.")

    # Pagination (operations=search/list)
    limit: int = Field(default=100, ge=1, le=250, description="Records per page.")
    after: str = Field(default="", description="Cursor returned by the previous page (next_cursor / next_offset).")
    return_all: bool = Field(default=False, description="Follow cursors until every record is retrieved.")
    max_pages: int = Field(default=10, ge=1, le=100, description="Upper bound on pages fetched when return_all is on.")
    property_names: list[str] = Field(
        default_factory=list,
        description="Properties to return (operation=list). Empty = the object's defaults.",
    )
    include_archived: bool = Field(default=False, description="Include archived records (operation=list).")

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

    async def test_connection(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Verify HubSpot connection by testing credentials against CRM v3."""
        import time
        start_t = time.perf_counter()
        try:
            resp = await self._provider.request(creds, "GET", "/crm/v3/objects/contacts", params={"limit": 1}, timeout=15.0)
            elapsed_ms = round((time.perf_counter() - start_t) * 1000, 2)
            if resp.status_code in (200, 204):
                return {"ok": True, "message": "Successfully connected to HubSpot CRM.", "latency_ms": elapsed_ms}
            return {"ok": False, "message": f"HubSpot returned status {resp.status_code}: {resp.text[:200]}", "latency_ms": elapsed_ms}
        except Exception as exc:
            return {"ok": False, "message": f"HubSpot connection test failed: {exc}"}

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
            if op == "list":
                return await self._op_list(creds, params, payload)
            if op == "get":
                return await self._op_get(creds, params, payload)
            if op == "create":
                return await self._op_create(creds, params, payload)
            if op == "update":
                return await self._op_update(creds, params, payload)
            if op == "delete":
                return await self._op_delete(creds, params, payload)
            if op == "get_properties":
                return await self._op_get_properties(creds, params, payload)
            if op == "associate_records":
                return await self._op_associate_records(creds, params, payload)
            if op == "get_owner":
                owner_id = self._require(self._raw(payload, "owner_id") or params.owner_id, "operation=get_owner requires owner_id.")
                return await self._provider.get_owner(creds, owner_id, timeout=params.timeout_seconds)
            if op == "list_pipelines":
                object_type = str(self._raw(payload, "object_type") or params.object_type)
                return await self._provider.list_pipelines(creds, object_type, timeout=params.timeout_seconds)
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

    @staticmethod
    def _paging(payload: dict[str, Any], params: HubSpotConnectorParams) -> dict[str, Any]:
        """Resolve pagination controls, preferring the raw payload (expressions)
        over the validated defaults so `{{ $json.next_cursor }}` works."""
        raw = payload or {}

        def _int(key: str, fallback: int, lo: int, hi: int) -> int:
            value = raw.get(key, fallback)
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                parsed = fallback
            return max(lo, min(hi, parsed))

        def _bool(key: str, fallback: bool) -> bool:
            value = raw.get(key, fallback)
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)

        return {
            "limit": _int("limit", params.limit, 1, 250),
            "after": str(raw.get("after", params.after) or "").strip() or None,
            "return_all": _bool("return_all", params.return_all),
            "max_pages": _int("max_pages", params.max_pages, 1, 100),
        }

    def _require(self, raw_value: Any, message: str) -> str:
        value = str(raw_value or "").strip()
        if not value:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, message, retryable=False)
        return value

    async def _op_search(self, creds: dict[str, Any], params: HubSpotConnectorParams, payload: dict[str, Any]) -> dict[str, Any]:
        ot = str(self._raw(payload, "object_type") or params.object_type)
        field_ = str(self._raw(payload, "search_field") or params.search_field)
        value = self._require(self._raw(payload, "search_value"), "operation=search requires a non-empty search value.")
        page = self._paging(payload, params)
        return await self._provider.search_records(
            creds, ot, field_, value,
            timeout=params.timeout_seconds,
            limit=min(page["limit"], 100),
            after=page["after"],
            return_all=page["return_all"],
            max_pages=page["max_pages"],
        )

    async def _op_list(self, creds: dict[str, Any], params: HubSpotConnectorParams, payload: dict[str, Any]) -> dict[str, Any]:
        ot = str(self._raw(payload, "object_type") or params.object_type)
        page = self._paging(payload, params)
        raw_props = self._raw(payload, "property_names")
        if raw_props is None:
            raw_props = params.property_names
        props = [str(p) for p in raw_props] if isinstance(raw_props, (list, tuple)) else []
        raw_archived = self._raw(payload, "include_archived")
        include_archived = params.include_archived if raw_archived is None else bool(raw_archived)
        return await self._provider.list_records(
            creds, ot,
            timeout=params.timeout_seconds,
            limit=page["limit"],
            after=page["after"],
            properties=props,
            archived=include_archived,
            return_all=page["return_all"],
            max_pages=page["max_pages"],
        )

    async def _op_delete(self, creds: dict[str, Any], params: HubSpotConnectorParams, payload: dict[str, Any]) -> dict[str, Any]:
        ot = str(self._raw(payload, "object_type") or params.object_type)
        rid = self._require(self._raw(payload, "record_id"), "operation=delete requires record_id.")
        return await self._provider.delete_record(creds, ot, rid, timeout=params.timeout_seconds)

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

    async def _op_get_properties(self, creds: dict[str, Any], params: HubSpotConnectorParams, payload: dict[str, Any]) -> dict[str, Any]:
        ot = str(self._raw(payload, "object_type") or params.object_type)
        return await self._provider.get_properties(creds, ot, timeout=params.timeout_seconds)

    async def _op_associate_records(self, creds: dict[str, Any], params: HubSpotConnectorParams, payload: dict[str, Any]) -> dict[str, Any]:
        from_ot = str(self._raw(payload, "from_object_type") or params.from_object_type)
        to_ot = str(self._raw(payload, "to_object_type") or params.to_object_type)
        from_id = self._require(self._raw(payload, "from_record_id") or params.from_record_id, "operation=associate_records requires from_record_id.")
        to_id = self._require(self._raw(payload, "to_record_id") or params.to_record_id, "operation=associate_records requires to_record_id.")
        assoc_id = str(self._raw(payload, "association_type_id") or params.association_type_id or "1")
        return await self._provider.associate_records(
            creds, from_ot, from_id, to_ot, to_id,
            association_type_id=assoc_id,
            timeout=params.timeout_seconds,
        )

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
