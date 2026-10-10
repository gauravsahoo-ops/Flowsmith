"""Pinecone Vector Database connector implementing ConnectorSDK."""

from __future__ import annotations

import logging
from typing import Any, Dict, List
import httpx

from app.connectors import (
    ConnectorSDK,
    ConnectorCategory,
    ConnectorHealthCheck,
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

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self.credentials: Dict[str, Any] = {}

    @property
    def node_types(self) -> List[str]:
        return ["pinecone"]

    async def connect(self, config: Dict[str, Any]) -> bool:
        self.credentials = config or {}
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
                healthy=False,
                message="Missing Pinecone API Key",
            )
        headers = self._get_headers(self.credentials)
        # H4: shared SSRF guard runs before every outbound call.
        from app.security.ssrf import assert_public_url

        url = "https://api.pinecone.io/indexes"
        try:
            await assert_public_url(url, node_id="pinecone")
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    return ConnectorHealthCheck(healthy=True, message="Pinecone connection active")
                return ConnectorHealthCheck(healthy=False, message=f"HTTP {res.status_code}")
        except Exception as e:
            return ConnectorHealthCheck(healthy=False, message=str(e))

    @staticmethod
    async def _index_host(host: str) -> str:
        """Normalize and validate a user-supplied index host (H4).

        Pinecone serves index hosts over https only — an http:// URL would
        send the API key in cleartext — and the result is handed to the
        shared SSRF guard before any request is built from it.
        """
        from app.security.ssrf import assert_public_url

        if not host.startswith("http"):
            host = f"https://{host}"
        if not host.startswith("https://"):
            raise make_connector_error(
                ConnectorErrorCode.VALIDATION_FAILED,
                "Pinecone index host must use https:// (the API key would be sent in cleartext).",
                retryable=False,
            )
        await assert_public_url(host, node_id="pinecone")
        return host

    async def op_execute(
        self,
        operation: str,
        payload: Dict[str, Any],
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        creds = (context or {}).get("credentials", {}).get("pinecone") or self.credentials or {}
        params = payload or {}
        api_key = creds.get("api_key") or ""
        if not api_key:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Pinecone API Key is required.",
                retryable=False,
            )

        headers = self._get_headers(creds)
        host = (params.get("host") or creds.get("host") or "").rstrip("/")
        timeout = float(params.get("timeout_seconds", 30.0))

        # H4: normalize + validate every outbound URL before any request is
        # built; the guards sit outside the try so NodeExecutionError
        # propagates unwrapped (the executor understands it directly).
        control_plane_url = "https://api.pinecone.io/indexes"
        if operation == "list_indexes":
            from app.security.ssrf import assert_public_url

            await assert_public_url(control_plane_url, node_id="pinecone")
        elif host:
            host = await self._index_host(host)

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                if operation == "list_indexes":
                    res = await client.get(control_plane_url, headers=headers)
                    res.raise_for_status()
                    return res.json()

                if not host:
                    raise make_connector_error(
                        ConnectorErrorCode.NOT_CONFIGURED,
                        "Pinecone Index host URL is required for vector operations.",
                        retryable=False,
                    )

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
                    raise make_connector_error(
                        ConnectorErrorCode.VALIDATION_FAILED,
                        f"Unsupported Pinecone operation: {operation}",
                        retryable=False,
                    )
            except ConnectorError:
                raise
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                code = (
                    ConnectorErrorCode.AUTH_FAILED
                    if status_code == 401
                    else ConnectorErrorCode.FORBIDDEN
                    if status_code == 403
                    else ConnectorErrorCode.NOT_FOUND
                    if status_code == 404
                    else ConnectorErrorCode.RATE_LIMITED
                    if status_code == 429
                    else ConnectorErrorCode.UNAVAILABLE
                    if status_code >= 500
                    else ConnectorErrorCode.BAD_REQUEST
                )
                raise make_connector_error(
                    code,
                    f"Pinecone API error: {e.response.text}",
                    retryable=status_code >= 500 or status_code == 429,
                ) from e
            except Exception as e:
                raise make_connector_error(
                    ConnectorErrorCode.BAD_REQUEST,
                    str(e),
                    retryable=False,
                ) from e
