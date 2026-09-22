"""Schedule connector implementing the ConnectorSDK interface.

A first-class connector for scheduled trigger operations, mirroring the
functionality of the existing schedule node but as a first-class entity
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


class ScheduleConnectorParams(BaseModel):
    """Parameters for a schedule connector operation."""

    cron: str = Field(min_length=1, description="The cron expression schedule.")
    timezone: str = Field(default="UTC", description="The timezone for the schedule.")
    timeout_seconds: float = 30.0


class ScheduleConnector(ConnectorSDK, ConnectorOperations):
    """Schedule connector - a first-class integration for scheduled triggers."""

    connector_id = "schedule"
    display_name = "Schedule Connector"
    description = "Handles scheduled trigger operations."
    category = "schedule"
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)

    async def connect(self, config: dict[str, Any]) -> bool:
        if "cron" not in config:
            return False
        self._metadata["cron"] = config["cron"]
        self._metadata["timezone"] = config.get("timezone", "UTC")
        self.status = "connected"
        return True

    async def disconnect(self) -> None:
        self.status = "disconnected"
        self._metadata.clear()

    @property
    def node_types(self) -> list[str]:
        return ["schedule"]

    async def op_execute(self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a schedule operation."""
        try:
            params = ScheduleConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid payload: {exc}",
                retryable=False,
            ) from exc

        # Schedule triggers fire at configured intervals.
        # For the framework, we return the schedule configuration.
        result: dict[str, Any] = {
            "status_code": 200,
            "headers": {},
            "body": {
                "cron": params.cron,
                "timezone": params.timezone,
                "next_fire": None,
            },
        }

        return {"output": result, "success": True, "operation": operation}

    async def op_health_check(self) -> ConnectorHealthCheck:
        return ConnectorHealthCheck(healthy=True, message="Schedule connector is operational.")

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
