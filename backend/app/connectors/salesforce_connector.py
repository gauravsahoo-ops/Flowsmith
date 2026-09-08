"""Salesforce connector implementing the ConnectorSDK interface.

The Salesforce Operation layer: maps connector operations (search,
query, get, create, update, upsert, delete, describe, list, bulk) onto
the SalesforceProviderClient (Phase 7/9), which owns all Salesforce
HTTP concerns: OAuth2 auth (refresh-token or password grant), instance
URL, API version, request construction, response parsing, error
translation (incl. Retry-After on 429) and pagination.

Layering:

    Salesforce Operation (this connector, op_execute)
        -> SalesforceProviderClient (app.providers.salesforce)
            -> SafeHTTPClient (SSRF-protected, redacted logging)
                -> Salesforce REST API

The engine never touches Salesforce HTTP code directly; it routes
'salesforce' node types to this connector, and credentials arrive via
the CredentialResolver in context["credentials"]["salesforce"].

Known limitation: duplicate-rule alert recovery after create re-queries
by Email only — objects without an Email field fall back to reporting
duplicate_alert without a resolved id.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorSDK,
    ConnectorError,
    ConnectorHealthCheck,
    ConnectorCategory,
    ConnectorStatus,
    ConnectorErrorCode,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations
from app.providers.salesforce import SalesforceProviderClient

logger = logging.getLogger(__name__)


class SalesforceConnectorParams(BaseModel):
    """Parameters for a Salesforce connector operation. Single source for 13 resources."""

    operation: str = Field(
        default="",
        description="Operation to run: search, query, get, create, update, upsert, delete, describe, list, bulk, custom_api_call, flow_invoke.",
    )
    resource: str = Field(default="", description="Salesforce resource, e.g. Account, Contact, CustomObject, Flow, CustomApiCall.")
    soql: str = Field(
        default="SELECT Id, Name, Type, LastModifiedDate FROM Account",
        description="SOQL query (operation=query). Unlimited by default — paginated via max_pages.",
    )
    object_name: str = Field(
        default="Account",
        description="Salesforce object API name, e.g. Account, Contact, Lead, or a custom object like My_Object__c.",
    )
    record_id: str = Field(default="", description="Record Id (operation=get/update/delete).")
    record: dict[str, Any] = Field(
        default_factory=dict,
        description="Field map for the record (operation=create/update/upsert).",
    )
    records: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Record batch for Bulk API 2.0 (operation=bulk).",
    )
    external_id_field: str = Field(
        default="",
        description="External-id field API name (operation=upsert; bulk_operation=upsert).",
    )
    external_id: str = Field(
        default="",
        description="External-id value of the record to upsert (operation=upsert).",
    )
    bulk_operation: str = Field(
        default="insert",
        description="Bulk ingest type: insert, update, upsert or delete (operation=bulk).",
    )
    max_pages: int = Field(
        default=100,
        ge=1,
        le=100,
        description="Maximum nextRecordsUrl pages followed for query results (operation=query). 100 ≈ unlimited (≈20k records).",
    )
    poll_interval_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=30,
        description="Delay between bulk job state polls (operation=bulk).",
    )
    max_polls: int = Field(
        default=60,
        ge=1,
        le=600,
        description="Maximum bulk job state polls before timing out (operation=bulk).",
    )
    search_field: str = Field(default="Email", description="Field to search on (operation=search).")
    search_value: str = Field(default="", description="Value to search for (operation=search).")
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    custom_api_url: str = Field(default="", description="Custom API path (operation=custom_api_call).")
    custom_api_method: str = Field(default="GET", description="HTTP method for custom_api_call.")
    custom_api_body: dict[str, Any] | None = Field(default=None, description="Body for custom_api_call.")
    flow_api_name: str = Field(default="", description="Flow API name (operation=flow_invoke).")
    flow_inputs: dict[str, Any] | None = Field(default=None, description="Flow inputs (operation=flow_invoke).")


class SalesforceConnector(ConnectorSDK, ConnectorOperations):
    """Salesforce connector - first-class integration for the Salesforce REST API."""

    connector_id = "salesforce"
    display_name = "Salesforce"
    description = "Query and manage records in a Salesforce org."
    category = ConnectorCategory.API
    version = "1.2.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = SalesforceProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["salesforce"]

    # ------------------------------------------------------------------
    # ConnectorSDK interface
    # ------------------------------------------------------------------

    async def connect(self, config: dict[str, Any]) -> bool:
        """Validate and store the Salesforce config (credential reference)."""
        if "instance_url" not in config:
            return False
        self._metadata["instance_url"] = config["instance_url"]
        self._metadata["api_version"] = config.get("api_version", "v63.0")
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
        """Execute a Salesforce operation.

        The payload is the node's resolved parameters; credentials arrive
        via context["credentials"]["salesforce"].
        """
        try:
            params = SalesforceConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid Salesforce payload: {exc}",
                retryable=False,
            ) from exc

        creds = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("salesforce") or {}
        # A usable credential needs app identity (either stored for manual
        # grants, or server-config-injected for 'Connect Salesforce' OAuth
        # connections) plus an auth method (username+password or refresh).
        has_app_identity = bool(creds.get("client_id")) or bool(creds.get("oauth"))
        has_auth_method = bool(creds.get("refresh_token")) or bool(
            creds.get("username") and creds.get("password")
        )
        if not has_app_identity or not has_auth_method:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Salesforce connector needs a 'salesforce' credential — connect it from the UI "
                "or provide client_id/client_secret and either username/password or a refresh_token.",
                retryable=False,
            )

        # --- No "execute" as Salesforce operation (engine generic) ---
        # Engine always calls op_execute("execute", payload) — real op is in payload["operation"] / payload["resource"]
        # Fix root cause: never treat first arg "execute" as Salesforce op; use payload's operation.
        # Curated UI aliases (Add Note → create, Get Many → query, etc.)
        _CURATED_ALIASES = {
            "add_note": "create",
            "add note": "create",
            "add note to an account": "create",
            "create or update": "upsert",
            "create_or_update": "upsert",
            "get many": "query",
            "get_many": "query",
            "get many accounts": "query",
            "get an account summary": "describe",
            "get_summary": "describe",
            "get summary": "describe",
            "custom": "custom_api_call",
            "custom api call": "custom_api_call",
        }
        raw_engine_op = (operation or "").lower().strip()
        raw_payload_op = (payload.get("operation") or params.operation or "").lower().strip()
        # Engine generic "execute" → use payload op
        if raw_engine_op == "execute":
            if not raw_payload_op:
                raise make_connector_error(
                    ConnectorErrorCode.BAD_REQUEST,
                    "Salesforce operation is required. Select a Resource and Operation before running. (got 'execute' as engine command, no Salesforce operation in payload)",
                    retryable=False,
                )
            raw_op = raw_payload_op
        else:
            raw_op = raw_engine_op or raw_payload_op
        if not raw_op:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "Salesforce operation is required. Select a Resource and Operation.",
                retryable=False,
            )
        # Curated alias → backend id (e.g. add_note → create)
        norm_op = _CURATED_ALIASES.get(raw_op, raw_op)
        # Keep params in sync for downstream helpers
        params.operation = _CURATED_ALIASES.get((params.operation or "").lower().strip(), (params.operation or "").lower().strip()) or norm_op
        if not params.operation:
            params.operation = norm_op
        # Special case is now handled, ensure not still "execute"
        if norm_op == "execute":
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "Unsupported Salesforce operation 'execute'. 'Execute Step' is the workflow command — the Salesforce Operation must be one of: Create, Create or Update, Delete, Get, Get Many, Get Summary, Update, Custom API Call, Search etc. Re-select the Operation in the node and Save.",
                retryable=False,
            )
        op = norm_op
        # Add Note fix-up
        if raw_op in ("add_note", "add note", "add note to an account") and (params.object_name or "").lower() in ("", "account"):
            params.object_name = "Note"
            # Ensure resource is Note-like for validation
            if not params.resource or params.resource.lower() == "account":
                params.resource = "Account"
        # --- Resource → Operation validation (single source) ---
        try:
            from app.connectors.salesforce_definition import RESOURCE_OPERATION_MATRIX  # local to avoid cycle
        except ImportError:
            RESOURCE_OPERATION_MATRIX = {}
        resource = (params.resource or payload.get("resource") or "").strip()
        # Default resource inference from object_name if not set (legacy nodes)
        if not resource:
            # Infer: if object_name is flow-like, treat as Flow; if custom_api_url set, CustomApiCall; else Account/CustomObject
            if params.flow_api_name:
                resource = "Flow"
            elif params.custom_api_url:
                resource = "CustomApiCall"
            elif (params.object_name or "").lower() in ("account","contact","lead","opportunity","case","task","attachment","document","user","note"):
                resource = params.object_name
            else:
                resource = "Account"
            params.resource = resource
        # Auto-correct: search/list/bulk/describe are global ops; if the
        # inferred resource doesn't support them, fall back to "Search".
        if op in ("search", "list") and resource.lower() not in ("search", "customapicall", "flow"):
            _allowed_for = RESOURCE_OPERATION_MATRIX.get(resource, [])
            if op not in _allowed_for:
                resource = "Search"
                params.resource = resource
        # Validate (allow curated aliases: get_many already normalized to query etc.)
        allowed = RESOURCE_OPERATION_MATRIX.get(resource, RESOURCE_OPERATION_MATRIX.get(resource.capitalize(), None))
        # also try case-insensitive
        if allowed is None:
            for k, v in RESOURCE_OPERATION_MATRIX.items():
                if k.lower() == resource.lower():
                    allowed = v
                    break
        if allowed is not None and op not in allowed:
            # bulk is a global SF operation — allowed for any sObject
            if op != "bulk":
                raise make_connector_error(
                    ConnectorErrorCode.BAD_REQUEST,
                    f"Salesforce operation '{op}' is not supported for resource '{resource}'. Supported for {resource}: {', '.join(allowed)}. Change the Operation or Resource and Save.",
                    retryable=False,
                )
        if resource and resource not in RESOURCE_OPERATION_MATRIX and resource.lower() not in [k.lower() for k in RESOURCE_OPERATION_MATRIX]:
            # Unknown resource — not in matrix, but still allow generic sObject if it's createable object_name
            if op in ("custom_api_call","flow_invoke","search","list","bulk","query","describe"):
                pass  # generic ops allowed for any resource
            else:
                logger.warning("Unknown Salesforce resource '%s' — proceeding with generic handler for op '%s'", resource, op)
        try:
            if op == "search":
                return await self._op_search(creds, params, payload)
            if op == "query":
                return await self._op_query(creds, params)
            if op == "get":
                return await self._op_get(creds, params)
            if op == "create":
                return await self._op_create(creds, params, payload)
            if op == "update":
                return await self._op_update(creds, params)
            if op == "upsert":
                return await self._op_upsert(creds, params)
            if op == "delete":
                return await self._op_delete(creds, params)
            if op == "describe":
                return await self._op_describe(creds, params)
            if op == "list":
                return await self._op_list(creds, params)
            if op == "bulk":
                return await self._op_bulk(creds, params)
            if op == "custom_api_call":
                return await self._op_custom_api_call(creds, params)
            if op == "flow_invoke":
                return await self._op_flow_invoke(creds, params)
        except ConnectorError:
            raise

        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST,
            f"Unsupported Salesforce operation '{raw_op}' (normalized '{op}'). Supported: search, get, create, update, upsert, delete, query, describe, list, bulk, custom_api_call, flow_invoke.",
            retryable=False,
        )

    async def _op_search(self, creds: dict[str, Any], params: SalesforceConnectorParams, payload: dict[str, Any]) -> dict[str, Any]:
        """Search/Get Record: find a record by field value (e.g. Lead by Email).

        Input validation uses the raw payload because the shared params
        model provides defaults (object_name, search_field) that must not
        mask missing inputs for search.
        """
        raw = payload or {}
        object_name = raw.get("object_name")
        search_field = raw.get("search_field")
        search_value = raw.get("search_value")
        if not object_name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(object_name)):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=search requires a valid object name (e.g. Lead).",
                retryable=False,
            )
        if not search_field or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(search_field)):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=search requires a valid search field (e.g. Email).",
                retryable=False,
            )
        if not search_value:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=search requires a non-empty search value.",
                retryable=False,
            )
        result = await self._provider.search_records(
            creds,
            object_name,
            search_field,
            search_value,
            timeout=params.timeout_seconds,
        )
        return {
            "output": {
                "found": result["found"],
                "record": result["record"],
                "object_name": params.object_name,
                "search_field": params.search_field,
            },
            "success": True,
            "operation": "search",
        }

    async def _op_query(self, creds: dict[str, Any], params: SalesforceConnectorParams) -> dict[str, Any]:
        body = await self._provider.query(
            creds, params.soql, timeout=params.timeout_seconds,
            max_pages=params.max_pages,
        )
        return {
            "output": {
                "records": body.get("records", []),
                "totalSize": body.get("totalSize", 0),
                "done": body.get("done", True),
                "nextRecordsUrl": body.get("nextRecordsUrl"),
            },
            "success": True,
            "operation": "query",
        }

    async def _op_get(self, creds: dict[str, Any], params: SalesforceConnectorParams) -> dict[str, Any]:
        if not params.record_id:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=get requires record_id.",
                retryable=False,
            )
        record = await self._provider.get_record(
            creds, params.object_name, params.record_id, timeout=params.timeout_seconds
        )
        return {
            "output": {"record": record},
            "success": True,
            "operation": "get",
        }

    async def _op_create(self, creds: dict[str, Any], params: SalesforceConnectorParams, payload: dict[str, Any]) -> dict[str, Any]:
        """Create Record.

        Create is non-idempotent: retrying an ambiguous failure (rate
        limit, timeout, 5xx) can silently duplicate the record, so every
        provider error is re-raised as non-retryable and the engine never
        auto-retries it (Phase 9).

        Input validation uses the raw payload because the shared params
        model provides a default object_name that must not mask a missing
        input for a write operation.
        """
        object_name = (payload or {}).get("object_name")
        if not object_name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(object_name)):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=create requires a valid object name (e.g. Lead).",
                retryable=False,
            )
        self._validate_record_fields(params.record, op="create")
        # Salesforce rejects create if 'Id' is in the body
        safe_record = {k: v for k, v in params.record.items() if k.lower() != "id"}
        try:
            body = await self._provider.create_record(
                creds, object_name, safe_record, timeout=params.timeout_seconds
            )
        except ConnectorError as exc:
            try:
                code = ConnectorErrorCode(exc.code)
            except ValueError:
                code = ConnectorErrorCode.BAD_REQUEST
            raise make_connector_error(
                code,
                str(exc),
                retryable=False,
            ) from exc
        output: dict[str, Any] = {"id": body.get("id"), "success": body.get("success", True)}
        if body.get("duplicate_alert"):
            output["duplicate_alert"] = True
            if body.get("matched_records"):
                output["matched_records"] = body["matched_records"]
        return {
            "output": output,
            "success": True,
            "operation": "create",
        }

    async def _op_update(self, creds: dict[str, Any], params: SalesforceConnectorParams) -> dict[str, Any]:
        """Update Record.

        Update is idempotent (re-applying the same fields is safe), so
        provider errors keep their retryable classification and the
        engine may retry (unlike create, Phase 9).
        """
        record_id = params.record_id or ""
        if not re.fullmatch(r"[A-Za-z0-9]{15}([A-Za-z0-9]{3})?", record_id):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=update requires a valid 15- or 18-character Salesforce record id.",
                retryable=False,
            )
        self._validate_record_fields(params.record, op="update")
        await self._provider.update_record(
            creds, params.object_name, record_id, params.record, timeout=params.timeout_seconds
        )
        return {"output": {"id": record_id, "success": True}, "success": True, "operation": "update"}

    async def _op_upsert(self, creds: dict[str, Any], params: SalesforceConnectorParams) -> dict[str, Any]:
        """Upsert Record by external id (Phase 9).

        Upsert is idempotent-safe: re-running the same upsert patches the
        same record instead of duplicating it, so provider errors keep
        their retryable classification and the engine may retry.
        """
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(params.external_id_field)):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=upsert requires a valid external_id_field API name.",
                retryable=False,
            )
        if not params.external_id:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=upsert requires external_id.",
                retryable=False,
            )
        self._validate_record_fields(params.record, op="upsert")
        # Strip Id from record body — external id is in the URL, not the body
        safe_record = {k: v for k, v in params.record.items() if k.lower() != "id"}
        result = await self._provider.upsert_record(
            creds, params.object_name, params.external_id_field,
            params.external_id, safe_record, timeout=params.timeout_seconds,
        )
        return {
            "output": {
                "id": result.get("id"),
                "created": result.get("created", False),
                "success": True,
            },
            "success": True,
            "operation": "upsert",
        }

    @staticmethod
    def _validate_record_fields(record: dict[str, Any], *, op: str) -> None:
        """Shared field-name/scalar validation for write operations."""
        if not isinstance(record, dict):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"operation={op} record must be a valid dict.",
                retryable=False,
            )
        if not record:
            # Keep the operation-specific phrasing users already see.
            if op == "update":
                detail = 'fields object (e.g. {"Company": "Updated Company"})'
            elif op == "create":
                detail = 'record object (e.g. {"FirstName": "Automation"})'
            else:
                detail = "record object"
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"operation={op} requires a non-empty {detail}.",
                retryable=False,
            )
        for field, value in record.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", str(field)):
                raise make_connector_error(
                    ConnectorErrorCode.BAD_REQUEST,
                    f"operation={op} has an invalid field name '{field}'.",
                    retryable=False,
                )
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise make_connector_error(
                    ConnectorErrorCode.BAD_REQUEST,
                    f"operation={op} field '{field}' must be a scalar value, got {type(value).__name__}.",
                    retryable=False,
                )

    async def _op_bulk(self, creds: dict[str, Any], params: SalesforceConnectorParams) -> dict[str, Any]:
        """Bulk load records via REST Bulk API 2.0 (Phase 9).

        insert is non-idempotent (a retried job would duplicate rows), so
        like single-record create the definition marks it non-retryable;
        update/upsert/delete are safe to retry.
        """
        object_name = params.object_name
        if not object_name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(object_name)):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=bulk requires a valid object name (e.g. Lead).",
                retryable=False,
            )
        if params.bulk_operation not in ("insert", "update", "upsert", "delete"):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=bulk requires bulk_operation in insert/update/upsert/delete.",
                retryable=False,
            )
        if not isinstance(params.records, list) or not params.records:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=bulk requires a non-empty records array.",
                retryable=False,
            )
        if len(params.records) > 10_000:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"operation=bulk supports at most 10000 records per job, got {len(params.records)}.",
                retryable=False,
            )
        for i, rec in enumerate(params.records):
            if not isinstance(rec, dict) or not rec:
                raise make_connector_error(
                    ConnectorErrorCode.BAD_REQUEST,
                    f"operation=bulk records[{i}] must be a non-empty object.",
                    retryable=False,
                )
        if params.bulk_operation == "delete":
            for i, rec in enumerate(params.records):
                if not rec.get("Id"):
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST,
                        f"operation=bulk delete requires records[{i}].Id.",
                        retryable=False,
                    )
        try:
            result = await self._provider.bulk_ingest(
                creds,
                object_name,
                params.bulk_operation,
                params.records,
                external_id_field=params.external_id_field,
                timeout=params.timeout_seconds,
                poll_interval=params.poll_interval_seconds,
                max_polls=params.max_polls,
            )
        except ConnectorError as exc:
            if params.bulk_operation != "insert":
                raise
            # Bulk insert mirrors single-record create semantics: a
            # retried job would duplicate every row, so any error is
            # surfaced as final (non-retryable).
            try:
                code = ConnectorErrorCode(exc.code)
            except ValueError:
                code = ConnectorErrorCode.BAD_REQUEST
            raise make_connector_error(code, str(exc), retryable=False) from exc
        output: dict[str, Any] = {
            "job_id": result.get("job_id"),
            "state": result.get("state"),
            "records_processed": result.get("records_processed", 0),
            "records_failed": result.get("records_failed", 0),
            # Stable contract: both lists are always present (empty on
            # success), matching the operation's output schema.
            "failed_records": result.get("failed_records") or [],
            "successful_records": result.get("successful_records") or [],
            "success": result.get("state") == "JobComplete",
        }
        if result.get("error_message"):
            output["error_message"] = result["error_message"]
        return {"output": output, "success": output["success"], "operation": "bulk"}

    async def _op_delete(self, creds: dict[str, Any], params: SalesforceConnectorParams) -> dict[str, Any]:
        if not params.record_id:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "operation=delete requires record_id.",
                retryable=False,
            )
        await self._provider.delete_record(
            creds, params.object_name, params.record_id, timeout=params.timeout_seconds
        )
        return {"output": {"id": params.record_id, "success": True}, "success": True, "operation": "delete"}

    async def _op_describe(self, creds: dict[str, Any], params: SalesforceConnectorParams) -> dict[str, Any]:
        """Field discovery (Phase 9): rich per-field metadata so the UI
        can render dynamic object/field configuration — picklists,
        required flags, reference targets and write-ability."""
        body = await self._provider.describe_object(
            creds, params.object_name, timeout=params.timeout_seconds
        )
        fields = []
        for f in body.get("fields", []):
            createable = bool(f.get("createable", False))
            fields.append({
                "name": f.get("name"),
                "label": f.get("label"),
                "type": f.get("type"),
                "createable": createable,
                "updateable": bool(f.get("updateable", False)),
                # Standard Salesforce "required on create": must be
                # createable, non-nillable, and not auto-defaulted.
                "required": (
                    createable
                    and not bool(f.get("nillable", True))
                    and not bool(f.get("defaultedOnCreate", False))
                ),
                "picklist_values": [
                    pv.get("value") for pv in (f.get("picklistValues") or [])
                    if isinstance(pv, dict) and pv.get("value") is not None
                ],
                "reference_to": f.get("referenceTo") or [],
            })
        return {
            "output": {
                "name": body.get("name"),
                "label": body.get("label"),
                "createable": bool(body.get("createable", False)),
                "updateable": bool(body.get("updateable", False)),
                "fields": fields,
            },
            "success": True,
            "operation": "describe",
        }

    async def _op_list(self, creds: dict[str, Any], params: SalesforceConnectorParams) -> dict[str, Any]:
        body = await self._provider.list_objects(
            creds, timeout=params.timeout_seconds
        )
        return {
            "output": {
                "sobjects": [
                    {"name": s.get("name"), "label": s.get("label"), "createable": s.get("createable")}
                    for s in body.get("sobjects", [])
                ]
            },
            "success": True,
            "operation": "list",
        }

    async def _op_custom_api_call(self, creds: dict[str, Any], params: SalesforceConnectorParams) -> dict[str, Any]:
        if not params.custom_api_url:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "Custom API Call requires 'custom_api_url' (e.g. /services/data/v63.0/sobjects/Account).",
                retryable=False,
            )
        method = (params.custom_api_method or "GET").upper()
        body = params.custom_api_body
        result = await self._provider.custom_api_call(
            creds, method, params.custom_api_url, body=body, timeout=params.timeout_seconds
        )
        return {"output": result, "success": True, "operation": "custom_api_call"}

    async def _op_flow_invoke(self, creds: dict[str, Any], params: SalesforceConnectorParams) -> dict[str, Any]:
        if not params.flow_api_name:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "Flow invoke requires 'flow_api_name' (e.g. My_Flow).",
                retryable=False,
            )
        result = await self._provider.invoke_flow(
            creds, params.flow_api_name, params.flow_inputs, timeout=params.timeout_seconds
        )
        return {"output": result.get("output", result), "success": True, "operation": "flow_invoke"}

    async def op_health_check(self) -> ConnectorHealthCheck:
        """Report the connector as operational when configured; a live
        check would need a credential, which only exists at run time."""
        if self.status == ConnectorStatus.CONNECTED and self._provider.has_token:
            return ConnectorHealthCheck(healthy=True, message="Salesforce connector is connected.")
        return ConnectorHealthCheck(
            healthy=False,
            message="Salesforce connector is not configured (needs a salesforce credential).",
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