"""Webhook connector implementing the ConnectorSDK interface.

A first-class connector for webhook trigger operations, mirroring the
functionality of the existing webhook node but as a first-class entity
manageable through the Connector Framework.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorSDK,
    ConnectorHealthCheck,
    ConnectorErrorCode,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations

logger = logging.getLogger(__name__)


class WebhookConnectorParams(BaseModel):
    """Parameters for a webhook connector operation."""

    trigger_type: str = "receive"  # "receive", "resend", "test"
    path: str = Field(min_length=1, description="The webhook path suffix.")
    method: str = "POST"
    timeout_seconds: float = 30.0


class WebhookConnector(ConnectorSDK, ConnectorOperations):
    """Webhook connector - a first-class integration for webhook triggers."""

    connector_id = "webhook"
    display_name = "Webhook Connector"
    description = "Handles webhook trigger operations."
    category = "webhook"
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)

    async def connect(self, config: dict[str, Any]) -> bool:
        if "path" not in config:
            return False
        self._metadata["path"] = config["path"]
        self._metadata["method"] = config.get("method", "POST")
        self.status = "connected"
        return True

    async def disconnect(self) -> None:
        self.status = "disconnected"
        self._metadata.clear()

    @property
    def node_types(self) -> list[str]:
        return ["webhook"]

    async def op_execute(self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a webhook operation."""
        try:
            params = WebhookConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid payload: {exc}",
                retryable=False,
            ) from exc

        # Webhook triggers don't make outbound HTTP calls in the same way
        # They receive inbound payloads. For the framework, we return
        # the configured path and trigger info.
        result: dict[str, Any] = {
            "status_code": 200,
            "headers": {},
            "body": {
                "trigger_type": params.trigger_type,
                "path": params.path,
                "method": params.method,
                "received_at": None,
            },
        }

        return {"output": result, "success": True, "operation": operation}

    async def op_health_check(self) -> ConnectorHealthCheck:
        return ConnectorHealthCheck(healthy=True, message="Webhook connector is operational.")

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
        return {
            "output": self.to_dict(),
            "success": True,
        }


# Auto-registration handled via get_registry().register() on import
