"""MongoDB connector implementing the ConnectorSDK interface.

Thin mapper over MongoProviderClient (PyMongo off-loop); credentials
arrive via context["credentials"]["mongodb"].
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorCategory,
    ConnectorError,
    ConnectorErrorCode,
    ConnectorSDK,
    ConnectorStatus,
    make_connector_error,
)
from app.providers.mongodb import MongoProviderClient


class MongoDBConnectorParams(BaseModel):
    operation: str = Field(default="find", description="find | insert_one | update_one | delete_one.")
    database: str = ""
    collection: str = ""
    filter: dict[str, Any] = Field(default_factory=dict)
    document: dict[str, Any] = Field(default_factory=dict)
    update: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=50, ge=1, le=500)
    skip: int = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class MongoDBConnector(ConnectorSDK):
    connector_id = "mongodb"
    display_name = "MongoDB"
    description = "Find and modify documents in MongoDB collections."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = MongoProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["mongodb"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("uri") or "").strip())

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = MongoDBConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid MongoDB payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("mongodb") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        database = str(raw.get("database") or params.database)
        collection = str(raw.get("collection") or params.collection)
        timeout = params.timeout_seconds

        def _obj(key: str) -> dict[str, Any]:
            value = raw.get(key)
            if isinstance(value, dict) and value:
                return value
            return getattr(params, key)

        try:
            if op == "find":
                return await self._provider.find(
                    creds, database, collection, filter_query=_obj("filter"),
                    limit=params.limit, skip=params.skip, timeout=timeout,
                )
            if op == "insert_one":
                return await self._provider.insert_one(
                    creds, database, collection, _obj("document"), timeout=timeout,
                )
            if op == "update_one":
                return await self._provider.update_one(
                    creds, database, collection, filter_query=_obj("filter"),
                    update=_obj("update"), timeout=timeout,
                )
            if op == "delete_one":
                return await self._provider.delete_one(
                    creds, database, collection, filter_query=_obj("filter"), timeout=timeout,
                )
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported MongoDB operation '{operation}'.", retryable=False,
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
