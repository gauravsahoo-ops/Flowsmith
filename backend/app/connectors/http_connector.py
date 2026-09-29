"""Example HTTP connector implementing the ConnectorSDK interface.

This mirrors the functionality of the existing http_request node but
as a first-class connector that can be registered, discovered, and
managed through the Connector Framework.

Uses SafeHTTPClient for all external API calls (spec 37.28).
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlencode

from app.security.safe_http_client import get_safe_http_client
import httpx
from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorSDK,
    ConnectorHealthCheck,
    ConnectorCategory,
    ConnectorErrorCode,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations

logger = logging.getLogger(__name__)


def infer_json_schema(data: Any) -> dict[str, Any]:
    """Infers dynamic JSON schema from any runtime response structure."""
    if data is None:
        return {"type": "null"}
    if isinstance(data, bool):
        return {"type": "boolean"}
    if isinstance(data, int):
        return {"type": "integer"}
    if isinstance(data, float):
        return {"type": "number"}
    if isinstance(data, str):
        return {"type": "string"}
    if isinstance(data, list):
        items_schema = infer_json_schema(data[0]) if data else {}
        return {"type": "array", "items": items_schema}
    if isinstance(data, dict):
        properties = {k: infer_json_schema(v) for k, v in data.items()}
        return {
            "type": "object",
            "properties": properties,
            "required": [k for k, v in data.items() if v is not None],
        }
    return {"type": "string"}


class HTTPConnectorParams(BaseModel):
    """Parameters for an HTTP connector operation supporting REST, GraphQL, SOAP, and advanced HTTP."""

    method: str = "GET"
    url: str = Field(min_length=1, description="The URL to call.")
    protocol: Literal["REST", "GRAPHQL", "SOAP"] = "REST"
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    path_params: dict[str, Any] = Field(default_factory=dict)
    body: Any = None
    form_data: Optional[dict[str, Any]] = None
    content_type: Optional[str] = None
    
    # GraphQL specific
    graphql_query: Optional[str] = None
    graphql_variables: Optional[dict[str, Any]] = None
    graphql_operation_name: Optional[str] = None

    # SOAP specific
    soap_action: Optional[str] = None
    soap_envelope: Optional[str] = None

    # Auth configuration
    auth_type: Optional[Literal["bearer", "basic", "api_key", "oauth2", "none"]] = None
    auth_token: Optional[str] = None
    auth_username: Optional[str] = None
    auth_password: Optional[str] = None
    auth_key_name: Optional[str] = None
    auth_key_in: Literal["header", "query"] = "header"

    # Execution controls
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_delay_seconds: float = 0.5
    idempotency_key: Optional[str] = None
    infer_schema: bool = False

    # Pagination controls
    paginate: bool = False
    pagination_type: Literal["offset", "page", "cursor"] = "page"
    page_param: str = "page"
    limit_param: str = "limit"
    page_size: int = 50
    max_pages: int = 1


class HTTPConnector(ConnectorSDK, ConnectorOperations):
    """Universal HTTP connector - covers REST, GraphQL, SOAP, and arbitrary public APIs with SSRF protection."""

    connector_id = "http"
    display_name = "Universal HTTP Connector"
    description = "Universal API adapter for REST, GraphQL, SOAP, and arbitrary external HTTP services."
    category = ConnectorCategory.API
    version = "2.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)

    # ------------------------------------------------------------------
    # ConnectorSDK interface
    # ------------------------------------------------------------------

    async def connect(self, config: dict[str, Any]) -> bool:
        """Validate and store the base URL / auth config for the connector."""
        try:
            if "base_url" not in config:
                return False
            self._metadata["base_url"] = config["base_url"]
            self._metadata["auth_type"] = config.get("auth_type", "none")
            self.status = "connected"
            return True
        except Exception as exc:
            logger.error("Universal HTTP connector connect failed: %s", exc)
            self.status = "error"
            return False

    async def disconnect(self) -> None:
        """Tear down the connector connection."""
        self.status = "disconnected"
        self._metadata.clear()

    @property
    def node_types(self) -> list[str]:
        return ["http_request"]

    # ------------------------------------------------------------------
    # ConnectorOperations implementations
    # ------------------------------------------------------------------

    async def op_execute(self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a universal HTTP request across REST, GraphQL, SOAP with SSRF protection and retries."""
        try:
            params = HTTPConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid payload for Universal HTTP request: {exc}",
                retryable=False,
            ) from exc

        base_url = self.get_metadata("base_url", "")
        full_url = params.url
        if base_url and not full_url.startswith(("http://", "https://")):
            full_url = f"{base_url.rstrip('/')}/{full_url.lstrip('/')}"

        # Interpolate path parameters
        if params.path_params:
            for k, v in params.path_params.items():
                full_url = full_url.replace(f"{{{k}}}", str(v))

        # Build headers
        req_headers: dict[str, str] = dict(params.headers)

        # Resolve credentials from context or params
        creds = (context or {}).get("credentials", {}).get("http", {}) if context else {}
        auth_type = params.auth_type or creds.get("auth_type")
        
        # Query params dict
        query_params: dict[str, Any] = dict(params.query_params)

        # Apply Authentication
        if auth_type == "bearer" or creds.get("api_key") or params.auth_token:
            token = params.auth_token or creds.get("api_key") or creds.get("access_token")
            if token:
                req_headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "basic" or (params.auth_username and params.auth_password):
            user = params.auth_username or creds.get("username", "")
            pwd = params.auth_password or creds.get("password", "")
            import base64
            token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
            req_headers["Authorization"] = f"Basic {token}"
        elif auth_type == "api_key" and (params.auth_token or creds.get("api_key")):
            key_name = params.auth_key_name or "X-API-Key"
            token = params.auth_token or creds.get("api_key")
            if params.auth_key_in == "query":
                query_params[key_name] = token
            else:
                req_headers[key_name] = token

        # Handle Protocol Variations
        req_method = params.method.upper()
        req_json: Any = None
        req_content: Any = None
        req_data: Any = None

        if params.protocol == "GRAPHQL":
            req_method = "POST"
            req_headers["Content-Type"] = "application/json"
            gql_payload: dict[str, Any] = {
                "query": params.graphql_query or (params.body if isinstance(params.body, str) else "")
            }
            if params.graphql_variables:
                gql_payload["variables"] = params.graphql_variables
            if params.graphql_operation_name:
                gql_payload["operationName"] = params.graphql_operation_name
            req_json = gql_payload

        elif params.protocol == "SOAP":
            req_method = "POST"
            req_headers["Content-Type"] = params.content_type or "text/xml; charset=utf-8"
            if params.soap_action:
                req_headers["SOAPAction"] = f'"{params.soap_action}"'
            req_content = (params.soap_envelope or str(params.body or "")).encode("utf-8")

        else:
            # REST protocol
            if params.form_data:
                req_data = params.form_data
                if params.content_type:
                    req_headers["Content-Type"] = params.content_type
            elif params.body is not None and params.body not in ("none", ""):
                if isinstance(params.body, (dict, list)):
                    req_json = params.body
                else:
                    req_content = str(params.body).encode("utf-8")
                    if params.content_type:
                        req_headers["Content-Type"] = params.content_type

        # Multi-page collector if pagination is requested
        pages_collected: list[dict[str, Any]] = []
        current_page = 1
        max_pages = params.max_pages if params.paginate else 1

        last_resp_body: Any = None
        last_status_code: int = 200
        last_headers: dict[str, str] = {}

        for page_idx in range(max_pages):
            step_query = dict(query_params)
            if params.paginate and max_pages > 1:
                if params.pagination_type == "page":
                    step_query[params.page_param] = current_page + page_idx
                    step_query[params.limit_param] = params.page_size
                elif params.pagination_type == "offset":
                    step_query[params.page_param] = page_idx * params.page_size
                    step_query[params.limit_param] = params.page_size

            # Retry loop with exponential backoff
            retries = 0
            while True:
                try:
                    async with get_safe_http_client() as client:
                        response = await client.request(
                            method=req_method,
                            url=full_url,
                            params=step_query if step_query else None,
                            json=req_json,
                            data=req_data if req_data is not None else req_content,
                            headers=req_headers,
                            timeout=httpx.Timeout(params.timeout_seconds),
                        )

                    # Handle 429 Rate Limit or 5xx Transient Errors
                    if response.status_code in (429, 502, 503, 504) and retries < params.max_retries:
                        retry_after = float(response.headers.get("Retry-After", params.retry_delay_seconds * (2 ** retries)))
                        retries += 1
                        logger.warning("HTTP %d received; retrying %d/%d after %0.2fs", response.status_code, retries, params.max_retries, retry_after)
                        await asyncio.sleep(min(retry_after, 5.0))
                        continue

                    last_status_code = response.status_code
                    last_headers = dict(response.headers)

                    try:
                        parsed_body = response.json()
                    except ValueError:
                        parsed_body = response.text

                    last_resp_body = parsed_body
                    pages_collected.append({
                        "page": page_idx + 1,
                        "status_code": last_status_code,
                        "body": parsed_body,
                    })
                    break

                except httpx.TimeoutException as exc:
                    if retries < params.max_retries:
                        retries += 1
                        await asyncio.sleep(params.retry_delay_seconds)
                        continue
                    raise make_connector_error(
                        ConnectorErrorCode.TIMEOUT,
                        f"Universal HTTP request timed out after {params.timeout_seconds}s.",
                        retryable=True,
                    ) from exc
                except httpx.RequestError as exc:
                    if retries < params.max_retries:
                        retries += 1
                        await asyncio.sleep(params.retry_delay_seconds)
                        continue
                    raise make_connector_error(
                        ConnectorErrorCode.UNAVAILABLE,
                        f"Universal HTTP request failed: {exc}",
                        retryable=True,
                    ) from exc

        # Assemble Output
        output_data: dict[str, Any] = {
            "status_code": last_status_code,
            "headers": last_headers,
            "body": last_resp_body if not params.paginate or max_pages == 1 else [p["body"] for p in pages_collected],
            "protocol": params.protocol,
        }

        if params.paginate and max_pages > 1:
            output_data["pagination"] = {
                "pages_fetched": len(pages_collected),
                "page_size": params.page_size,
            }

        # Dynamic Schema Inference
        if params.infer_schema and last_resp_body:
            output_data["inferred_schema"] = infer_json_schema(last_resp_body)

        # Cache for idempotent methods
        if params.idempotency_key and context and "storage" in context:
            await context["storage"].set(
                f"idem:{params.idempotency_key}",
                output_data,
                ttl=86400,
            )

        return {"output": output_data, "success": last_status_code < 400, "operation": operation}

    async def op_search(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Search operation - GET request with query params."""
        return await self.op_execute("search", payload, context)

    async def op_query(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """QUERY operation - GET request with query params."""
        payload_copy = dict(payload) if payload else {}
        payload_copy.setdefault("method", "GET")
        return await self.op_execute("query", payload_copy, context)

    async def op_get(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET operation."""
        payload_copy = dict(payload) if payload else {}
        payload_copy["method"] = "GET"
        return await self.op_execute("get", payload_copy, context)

    async def op_create(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """CREATE operation - POST."""
        payload_copy = dict(payload) if payload else {}
        payload_copy["method"] = "POST"
        return await self.op_execute("create", payload_copy, context)

    async def op_update(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """UPDATE operation - PUT/PATCH."""
        payload_copy = dict(payload) if payload else {}
        payload_copy["method"] = payload_copy.get("method", "PUT")
        return await self.op_execute("update", payload_copy, context)

    async def op_delete(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """DELETE operation."""
        payload_copy = dict(payload) if payload else {}
        payload_copy["method"] = "DELETE"
        return await self.op_execute("delete", payload_copy, context)

    async def op_health_check(self) -> ConnectorHealthCheck:
        """Ping a well-known health endpoint."""
        base_url = self.get_metadata("base_url", "")
        if not base_url:
            return ConnectorHealthCheck(healthy=False, message="Connector not configured.")

        try:
            async with get_safe_http_client() as client:
                resp = await client.get(f"{base_url.rstrip('/')}/health", timeout=5.0)
                if resp.status_code == 200:
                    return ConnectorHealthCheck(healthy=True, message="Connector is healthy.")
                return ConnectorHealthCheck(healthy=False, message=f"Health endpoint returned {resp.status_code}")
        except Exception as exc:
            return ConnectorHealthCheck(healthy=False, message=f"Health check failed: {exc}")

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """List operation - return connector metadata."""
        return {
            "output": {
                "connector_id": self.connector_id,
                "name": self.name,
                "status": self.status,
                "metadata": self._metadata,
                "protocols": ["REST", "GRAPHQL", "SOAP"],
            },
            "success": True,
        }

    async def op_describe(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Describe operation - return connector info."""
        return {
            "output": self.to_dict(),
            "success": True,
        }

