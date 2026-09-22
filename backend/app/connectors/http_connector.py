"""Example HTTP connector implementing the ConnectorSDK interface.

This mirrors the functionality of the existing http_request node but
as a first-class connector that can be registered, discovered, and
managed through the Connector Framework.

Uses SafeHTTPClient for all external API calls (spec 37.28).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

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


class HTTPConnectorParams(BaseModel):
    """Parameters for an HTTP connector operation."""

    method: str = "GET"
    url: str = Field(min_length=1, description="The URL to call.")
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    timeout_seconds: float = 30.0
    idempotency_key: Optional[str] = None


class HTTPConnector(ConnectorSDK, ConnectorOperations):
    """HTTP connector - a first-class integration for REST API calls."""

    connector_id = "http"
    display_name = "HTTP Connector"
    description = "Calls any REST API endpoint."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)

    # ------------------------------------------------------------------
    # ConnectorSDK interface
    # ------------------------------------------------------------------

    async def connect(self, config: dict[str, Any]) -> bool:
        """Validate and store the base URL / auth config for the connector.

        In this simple example we just validate the config structure.
        A real implementation might establish a persistent connection.
        """
        try:
            # Validate required fields
            if "base_url" not in config:
                return False
            self._metadata["base_url"] = config["base_url"]
            self._metadata["auth_type"] = config.get("auth_type", "none")
            self.status = "connected"
            return True
        except Exception as exc:
            logger.error("HTTP connector connect failed: %s", exc)
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
        """Execute an HTTP request.

        Operation name is typically "request" or the HTTP method.
        Uses SafeHTTPClient for all external API calls (spec 37.28).
        """
        try:
            params = HTTPConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid payload: {exc}",
                retryable=False,
            ) from exc

        base_url = self.get_metadata("base_url", "")
        if not base_url:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "HTTP connector not configured with a base_url",
                retryable=False,
            )

        # Build full URL
        full_url = params.url
        if base_url and not full_url.startswith(("http://", "https://")):
            full_url = f"{base_url.rstrip('/')}/{full_url.lstrip('/')}"

        # Resolve credential if referenced
        creds = None
        if context and "credentials" in context:
            creds = context["credentials"].get("http")

        # Build SafeHTTPClient kwargs
        http_client_kwargs: dict[str, Any] = {}

        if creds and creds.get("api_key"):
            # Add authorization header - SafeHTTPClient will redact it from logs
            http_client_kwargs["headers"] = {**params.headers, "Authorization": f"Bearer {creds['api_key']}"}
        else:
            http_client_kwargs["headers"] = params.headers

        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method=params.method,
                    url=full_url,
                    json=params.body if params.body not in (None, "none") else None,
                    timeout=httpx.Timeout(params.timeout_seconds),
                    **http_client_kwargs,
                )
        except httpx.TimeoutException as exc:
            raise make_connector_error(
                ConnectorErrorCode.TIMEOUT,
                f"HTTP request timed out after {params.timeout_seconds}s.",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"HTTP request failed: {exc}",
                retryable=True,
            ) from exc

        # Parse response
        try:
            body = response.json()
        except ValueError:
            body = response.text

        result: dict[str, Any] = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": body,
        }

        # Cache for idempotent methods
        if params.idempotency_key:
            # Store in context storage if available
            if context and "storage" in context:
                await context["storage"].set(
                    f"idem:{params.idempotency_key}",
                    result,
                    ttl=86400,
                )

        return {"output": result, "success": True, "operation": operation}

    async def op_search(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Search operation - alias for execute with method=GET."""
        return await self.op_execute("get", payload, context)

    async def op_get(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET operation."""
        payload_copy = dict(payload) if payload else {}
        payload_copy["method"] = "GET"
        return await self.op_execute("request", payload_copy, context)

    async def op_create(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """CREATE operation - POST."""
        payload_copy = dict(payload) if payload else {}
        payload_copy["method"] = "POST"
        return await self.op_execute("request", payload_copy, context)

    async def op_update(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """UPDATE operation - PUT/PATCH."""
        payload_copy = dict(payload) if payload else {}
        payload_copy["method"] = "PUT"
        return await self.op_execute("request", payload_copy, context)

    async def op_delete(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """DELETE operation."""
        payload_copy = dict(payload) if payload else {}
        payload_copy["method"] = "DELETE"
        return await self.op_execute("request", payload_copy, context)

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
        """List operation - not typically used for HTTP, return connector metadata."""
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
        """Describe operation - return connector info."""
        return {
            "output": self.to_dict(),
            "success": True,
        }


# Auto-registration is handled manually via get_registry().register()
# when the module is imported in the application startup path.
