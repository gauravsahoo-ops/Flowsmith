"""Elasticsearch & OpenSearch node (Phase 14 Core Node).

Runs search queries, indexes documents, and inspects cluster health on
Elasticsearch or OpenSearch clusters using REST APIs and SafeHttpClient.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from app.security.safe_http_client import SafeHTTPClient


class ElasticsearchParams(BaseModel):
    operation: Literal[
        "search",
        "index_document",
        "get_document",
        "delete_document",
        "cluster_health"
    ] = Field(default="search", description="Elasticsearch operation.")
    index: str = Field(default="", description="Target index or alias name.")
    document_id: str = Field(default="", description="Document ID (for get, index, or delete).")
    query: dict[str, Any] | str = Field(
        default_factory=lambda: {"query": {"match_all": {}}},
        description="Search query DSL (JSON or dict)."
    )
    document: dict[str, Any] | str = Field(
        default_factory=dict,
        description="Document body for index_document."
    )
    size: int = Field(default=10, ge=1, le=1000, description="Max documents to return.")


@register
class ElasticsearchNode(BaseNode[ElasticsearchParams]):
    node_type = "elasticsearch"
    display_name = "Elasticsearch"
    version = 1
    description = "Execute search queries, index documents, and manage Elasticsearch or OpenSearch clusters"
    category = "Database"
    icon = "elasticsearch"
    parameters_schema = ElasticsearchParams
    credential_types = ["elasticsearch", "http"]
    input_handles = ["main"]
    output_handles = ["main"]
    idempotency = "conditionally_idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: ElasticsearchParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        creds = (ctx.credentials or {}).get("elasticsearch") or (ctx.credentials or {}).get("http") or {}
        base_url = (creds.get("base_url") or creds.get("endpoint") or "http://localhost:9200").rstrip("/")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        api_key = creds.get("api_key")
        bearer_token = creds.get("bearer_token") or creds.get("token")
        username = creds.get("username")
        password = creds.get("password")

        if api_key:
            headers["Authorization"] = f"ApiKey {api_key}"
        elif bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        elif username and password:
            import base64
            auth_val = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {auth_val}"

        op = params.operation
        async with SafeHTTPClient(timeout_s=30.0) as client:
            try:
                if op == "cluster_health":
                    url = f"{base_url}/_cluster/health"
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    return NodeResult(output_items=[resp.json()])

                if not params.index and op != "cluster_health":
                    raise NodeExecutionError(
                        "Index name is required for Elasticsearch operations.",
                        code="MISSING_INDEX",
                        node_id="elasticsearch",
                        retryable=False,
                    )

                if op == "search":
                    url = f"{base_url}/{params.index}/_search"
                    query_body: Any = params.query
                    if isinstance(query_body, str):
                        query_body = json.loads(query_body) if query_body.strip() else {"query": {"match_all": {}}}
                    if "size" not in query_body:
                        query_body["size"] = params.size

                    resp = await client.post(url, headers=headers, json=query_body)
                    resp.raise_for_status()
                    data = resp.json()
                    hits = data.get("hits", {}).get("hits", [])
                    output_items = [
                        {
                            "_id": h.get("_id"),
                            "_index": h.get("_index"),
                            "_score": h.get("_score"),
                            **h.get("_source", {}),
                        }
                        for h in hits
                    ]
                    return NodeResult(output_items=output_items if output_items else [{"total_hits": 0, "hits": []}])

                elif op == "get_document":
                    if not params.document_id:
                        raise NodeExecutionError(
                            "Document ID is required for get_document.",
                            code="MISSING_DOCUMENT_ID",
                            node_id="elasticsearch",
                            retryable=False,
                        )
                    url = f"{base_url}/{params.index}/_doc/{params.document_id}"
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 404:
                        return NodeResult(output_items=[{"found": False, "_id": params.document_id}])
                    resp.raise_for_status()
                    data = resp.json()
                    return NodeResult(output_items=[{"_id": data.get("_id"), "found": True, **data.get("_source", {})}])

                elif op == "index_document":
                    doc_body = params.document
                    if isinstance(doc_body, str):
                        doc_body = json.loads(doc_body) if doc_body.strip() else {}
                    if not doc_body and input_items:
                        doc_body = input_items[0]

                    if params.document_id:
                        url = f"{base_url}/{params.index}/_doc/{params.document_id}"
                        resp = await client.put(url, headers=headers, json=doc_body)
                    else:
                        url = f"{base_url}/{params.index}/_doc"
                        resp = await client.post(url, headers=headers, json=doc_body)
                    resp.raise_for_status()
                    return NodeResult(output_items=[resp.json()])

                elif op == "delete_document":
                    if not params.document_id:
                        raise NodeExecutionError(
                            "Document ID is required for delete_document.",
                            code="MISSING_DOCUMENT_ID",
                            node_id="elasticsearch",
                            retryable=False,
                        )
                    url = f"{base_url}/{params.index}/_doc/{params.document_id}"
                    resp = await client.delete(url, headers=headers)
                    resp.raise_for_status()
                    return NodeResult(output_items=[resp.json()])

                else:
                    raise NodeExecutionError(
                        f"Unsupported Elasticsearch operation: {op}",
                        code="UNSUPPORTED_OPERATION",
                        node_id="elasticsearch",
                        retryable=False,
                    )
            except NodeExecutionError:
                raise
            except Exception as exc:
                raise NodeExecutionError(
                    f"Elasticsearch request failed: {exc}",
                    code="ELASTICSEARCH_ERROR",
                    node_id="elasticsearch",
                    retryable=True,
                ) from exc
