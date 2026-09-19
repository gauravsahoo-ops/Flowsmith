"""Pinecone Vector Database connector implementing ConnectorSDK."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx

from app.connectors import (
    ConnectorSDK,
    ConnectorCategory,
    ConnectorHealthCheck,
    ConnectorStatus,
    ConnectorError,
    ConnectorErrorCode,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations

logger = logging.getLogger(__name__)


class PineconeConnector(ConnectorSDK, ConnectorOperations):
    """Pinecone connector for vector embeddings storage and semantic similarity search."""

    connector_id = "pinecone"
    display_name = "Pinecone"
    description = "Upsert embeddings, query nearest neighbors, and manage vector indexes in Pinecone."
    category = ConnectorCategory.API
    version = "1.0.0"
    node_types = ["pinecone"]

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self.credentials: Dict[str, Any] = {}

    async def connect(self, credentials: Dict[str, Any]) -> bool:
        self.credentials = credentials or {}
        return True

    async def disconnect(self) -> None:
        self.credentials = {}

    def _get_headers(self, creds: Dict[str, Any]) -> Dict[str, str]:
        key = creds.get("api_key") or ""
        return {
            "Api-Key": key,
            "Content-Type": "application/json",
            "X-Pinecone-API-Version": "2024-07",
        }

    async def op_health_check(self) -> ConnectorHealthCheck:
        api_key = self.credentials.get("api_key") or ""
        if not api_key:
            return ConnectorHealthCheck(
                status=ConnectorStatus.UNHEALTHY,
                message="Missing Pinecone API Key",
            )
        headers = self._get_headers(self.credentials)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://api.pinecone.io/indexes", headers=headers)
                if res.status_code == 200:
                    return ConnectorHealthCheck(status=ConnectorStatus.HEALTHY, message="Pinecone connection active")
                return ConnectorHealthCheck(status=ConnectorStatus.UNHEALTHY, message=f"HTTP {res.status_code}")
        except Exception as e:
            return ConnectorHealthCheck(status=ConnectorStatus.UNHEALTHY, message=str(e))

    async def op_execute(self, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        creds = self.credentials or {}
        api_key = creds.get("api_key") or ""
        if not api_key:
            raise make_connector_error("Pinecone API Key is required.", code=ConnectorErrorCode.CONFIG_MISSING)

        headers = self._get_headers(creds)
        host = (params.get("host") or creds.get("host") or "").rstrip("/")
        timeout = float(params.get("timeout_seconds", 30.0))

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                if operation == "list_indexes":
                    res = await client.get("https://api.pinecone.io/indexes", headers=headers)
                    res.raise_for_status()
                    return res.json()

                if not host:
                    raise make_connector_error("Pinecone Index host URL is required for vector operations.", code=ConnectorErrorCode.CONFIG_MISSING)

                if not host.startswith("http"):
                    host = f"https://{host}"

                if operation == "upsert_vectors":
                    vectors = params.get("vectors") or []
                    namespace = params.get("namespace", "")
                    body: Dict[str, Any] = {"vectors": vectors}
                    if namespace:
                        body["namespace"] = namespace
                    res = await client.post(f"{host}/vectors/upsert", headers=headers, json=body)
                    res.raise_for_status()
                    return res.json()

                elif operation == "query_vectors":
                    vector = params.get("vector") or []
                    top_k = int(params.get("top_k", 10))
                    namespace = params.get("namespace", "")
                    filter_expr = params.get("filter")
                    include_metadata = bool(params.get("include_metadata", True))
                    include_values = bool(params.get("include_values", False))

                    body = {
                        "vector": vector,
                        "topK": top_k,
                        "includeMetadata": include_metadata,
                        "includeValues": include_values,
                    }
                    if namespace:
                        body["namespace"] = namespace
                    if filter_expr:
                        body["filter"] = filter_expr

                    res = await client.post(f"{host}/query", headers=headers, json=body)
                    res.raise_for_status()
                    return res.json()

                elif operation == "describe_index_stats":
                    res = await client.post(f"{host}/describe_index_stats", headers=headers, json={})
                    res.raise_for_status()
                    return res.json()

                elif operation == "delete_vectors":
                    ids = params.get("ids") or []
                    delete_all = bool(params.get("delete_all", False))
                    namespace = params.get("namespace", "")
                    body = {}
                    if delete_all:
                        body["deleteAll"] = True
                    elif ids:
                        body["ids"] = ids
                    if namespace:
                        body["namespace"] = namespace

                    res = await client.post(f"{host}/vectors/delete", headers=headers, json=body)
                    res.raise_for_status()
                    return res.json()

                elif operation == "health_check":
                    check = await self.op_health_check()
                    return check.model_dump()

                else:
                    raise make_connector_error(f"Unsupported Pinecone operation: {operation}", code=ConnectorErrorCode.VALIDATION_FAILED)
            except httpx.HTTPStatusError as e:
                raise make_connector_error(f"Pinecone API error: {e.response.text}", code=ConnectorErrorCode.REMOTE_ERROR)
            except Exception as e:
                raise make_connector_error(str(e), code=ConnectorErrorCode.EXECUTION_FAILED)
