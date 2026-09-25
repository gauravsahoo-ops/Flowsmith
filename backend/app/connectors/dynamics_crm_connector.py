"""Microsoft Dynamics 365 CRM connector implementing ConnectorSDK.

Maps connector operations (query, search, get, create, update, upsert,
delete, execute_action) onto the DynamicsCrmProviderClient.
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
from app.providers.dynamics_crm import DynamicsCrmProviderClient, normalize_entity_set

logger = logging.getLogger(__name__)


class DynamicsCrmConnectorParams(BaseModel):
    """Parameters for a Microsoft Dynamics 365 connector operation."""

    operation: str = Field(
        default="query",
        description="Operation: query, search, get, create, update, upsert, delete, execute_action.",
    )
    entity: str = Field(
        default="contacts",
        description="Target table or entity set (e.g. contacts, accounts, leads, incidents).",
    )
    record_id: str = Field(
        default="",
        description="Primary key GUID of the record (for get, update, delete).",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Record attributes and field values (for create, update, upsert).",
    )
    filter: str = Field(
        default="",
        description="OData filter query string ($filter).",
    )
    select: str | list[str] = Field(
        default="",
        description="Comma-separated or list of attributes to return ($select).",
    )
    expand: str = Field(
        default="",
        description="Navigation properties to expand ($expand).",
    )
    orderby: str = Field(
        default="",
        description="Sort order expression ($orderby).",
    )
    top: int = Field(
        default=50,
        description="Maximum records to return ($top).",
    )
    fetch_xml: str = Field(
        default="",
        description="Raw FetchXML query (overrides OData parameters if specified).",
    )
    key_field: str = Field(
        default="",
        description="Alternate key column name (for upsert).",
    )
    key_value: str = Field(
        default="",
        description="Alternate key value (for upsert).",
    )
    action_name: str = Field(
        default="",
        description="Name of custom or unbound Dataverse action (for execute_action).",
    )
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class DynamicsCrmConnector(ConnectorSDK, ConnectorOperations):
    """Microsoft Dynamics 365 connector (Dataverse Web API v9.2)."""

    connector_id = "dynamics_crm"
    display_name = "Microsoft Dynamics 365"
    description = "Query, search, create, update, and manage records in Microsoft Dynamics 365 CRM."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = DynamicsCrmProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["dynamics_crm"]

    # ------------------------------------------------------------------
    # ConnectorSDK Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, config: dict[str, Any]) -> bool:
        if not config.get("instance_url"):
            self.status = ConnectorStatus.ERROR
            return False
        try:
            await self._provider.who_am_i(config)
            self.status = ConnectorStatus.CONNECTED
            return True
        except Exception as exc:
            logger.warning("Dynamics 365 connect check failed: %s", exc)
            self.status = ConnectorStatus.ERROR
            return False

    async def disconnect(self) -> bool:
        self._provider.reset()
        self.status = ConnectorStatus.DISCONNECTED
        return True

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        """Test connection by calling WhoAmI on the Dataverse instance."""
        try:
            res = await self._provider.who_am_i(config)
            org_id = res.get("OrganizationId", "")
            user_id = res.get("UserId", "")
            return {"ok": True, "message": f"Connected to Dynamics 365 (Org: {org_id}, User: {user_id})"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    # ------------------------------------------------------------------
    # Operation Execution
    # ------------------------------------------------------------------

    async def op_execute(
        self,
        operation: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> Any:
        """Dispatch operation to DynamicsCrmProviderClient with resolved credentials."""
        creds = (
            context.get("credentials", {}).get("dynamics_crm")
            or context.get("credentials", {})
            or {}
        )
        if not creds:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Dynamics 365 node requires credentials. Connect via Credentials page.",
                retryable=False,
            )

        # Resolve real operation: Flowsmith engine calls connector.op_execute("execute", payload, context),
        # so prefer params["operation"] whenever operation is "execute" or blank.
        raw_op = (operation or "").lower().strip()
        payload_op = str(params.get("operation") or "").lower().strip()
        effective_op = payload_op if (raw_op in ("", "execute") and payload_op) else (raw_op or payload_op or "query")

        # Merge top-level params
        parsed_params = DynamicsCrmConnectorParams(**{**params, "operation": effective_op})
        op = effective_op
        entity = normalize_entity_set(parsed_params.entity)

        if op in ("query", "search"):
            filter_expr = parsed_params.filter
            if op == "search" and not filter_expr:
                term = str(params.get("query") or params.get("search_term") or params.get("term") or "").strip()
                if term:
                    if entity in ("contacts", "systemusers"):
                        filter_expr = f"contains(fullname, '{term}') or contains(emailaddress1, '{term}')"
                    elif entity == "leads":
                        filter_expr = f"contains(fullname, '{term}') or contains(companyname, '{term}')"
                    elif entity == "incidents":
                        filter_expr = f"contains(title, '{term}') or contains(ticketnumber, '{term}')"
                    else:
                        filter_expr = f"contains(name, '{term}')"

            records = await self._provider.query(
                creds,
                entity,
                filter_expr=filter_expr,
                select=parsed_params.select,
                expand=parsed_params.expand,
                orderby=parsed_params.orderby,
                top=parsed_params.top,
                fetch_xml=parsed_params.fetch_xml,
            )
            return {"records": records, "count": len(records), "entity": entity}

        if op == "get":
            record = await self._provider.get_record(
                creds,
                entity,
                parsed_params.record_id,
                select=parsed_params.select,
                expand=parsed_params.expand,
            )
            return record

        # Helper to extract data from various payload conventions
        def _extract_data(p: DynamicsCrmConnectorParams, raw: dict[str, Any]) -> dict[str, Any]:
            if p.data and isinstance(p.data, dict) and p.data:
                return p.data
            for key in ("properties", "fields", "attributes", "record"):
                val = raw.get(key)
                if isinstance(val, dict) and val:
                    return val
            # Fallback: any unknown fields outside DynamicsCrmConnectorParams schema
            exclude = set(DynamicsCrmConnectorParams.model_fields.keys()) | {"operation", "credentials"}
            extra = {k: v for k, v in raw.items() if k not in exclude}
            return extra or {}

        if op == "create":
            data = _extract_data(parsed_params, params)
            result = await self._provider.create_record(creds, entity, data)
            return result

        if op == "update":
            data = _extract_data(parsed_params, params)
            result = await self._provider.update_record(
                creds, entity, parsed_params.record_id, data
            )
            return result

        if op == "upsert":
            data = _extract_data(parsed_params, params)
            result = await self._provider.upsert_record(
                creds,
                entity,
                parsed_params.key_field,
                parsed_params.key_value,
                data,
            )
            return result

        if op == "delete":
            result = await self._provider.delete_record(creds, entity, parsed_params.record_id)
            return result

        if op == "execute_action":
            payload = parsed_params.data or {}
            result = await self._provider.execute_action(
                creds, parsed_params.action_name, payload
            )
            return result

        raise make_connector_error(
            ConnectorErrorCode.INVALID_OPERATION,
            f"Unsupported Dynamics 365 operation '{op}'. Supported: query, search, get, create, update, upsert, delete, execute_action.",
            retryable=False,
        )
