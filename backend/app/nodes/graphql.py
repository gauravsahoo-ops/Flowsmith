"""GraphQL node (Phase 43).

Sends a GraphQL query/mutation to an endpoint via POST and returns the
`data` payload. GraphQL `errors` entries become typed non-retryable
errors (per the GraphQL spec they are application-level failures even
over HTTP 200).
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import CONDITIONALLY_IDEMPOTENT, BaseNode, NodeContext, NodeResult, filter_client_kwargs
from app.nodes.registry import register


class GraphQLParams(BaseModel):
    url: str = Field(min_length=1, description="GraphQL endpoint URL.")
    query: str = Field(min_length=1, description="GraphQL query or mutation string.")
    variables: dict[str, Any] = Field(default_factory=dict)
    operation_name: str = Field(default="", description="Optional operationName.")
    headers: dict[str, str] = Field(default_factory=dict)

    auth_type: Literal["none", "bearer", "api_key"] = "none"
    auth_token: str = Field(default="", description="Bearer token / API key value.")
    api_key_name: str = Field(default="X-API-Key")

    timeout_seconds: float = 30.0
    max_response_bytes: int = Field(default=10 * 1024 * 1024, ge=1)


@register
class GraphQLNode(BaseNode[GraphQLParams]):
    node_type = "graphql"
    display_name = "GraphQL"
    version = 1
    description = "Execute a GraphQL query or mutation against any endpoint."
    category = "Actions"
    icon = "graphql"
    parameters_schema = GraphQLParams
    credential_types = ["http"]
    idempotency = CONDITIONALLY_IDEMPOTENT

    def _auth_headers(self, p: GraphQLParams) -> dict[str, str]:
        if p.auth_type == "bearer":
            token = p.auth_token.strip()
            if not token:
                raise NodeExecutionError("auth_type=bearer requires auth_token.", code="BAD_REQUEST",
                                         node_id=self.node_type, retryable=False)
            return {"Authorization": f"Bearer {token}"}
        if p.auth_type == "api_key":
            key = p.api_key_name.strip() or "X-API-Key"
            token = p.auth_token.strip()
            if not token:
                raise NodeExecutionError("auth_type=api_key requires auth_token.", code="BAD_REQUEST",
                                         node_id=self.node_type, retryable=False)
            return {key: token}
        return {}

    async def run(
        self,
        ctx: NodeContext,
        params: GraphQLParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        headers = {**self._auth_headers(params), **(params.headers or {})}
        payload: dict[str, Any] = {"query": params.query, "variables": params.variables}
        if params.operation_name:
            payload["operationName"] = params.operation_name

        try:
            # S10: SSRF protection — block internal/private IPs
            from app.nodes.http_request import HTTPRequestNode
            if params.url and "{{" not in params.url:
                HTTPRequestNode._validate_url_ssrf(params.url)  # type: ignore[attr-defined]
            kwargs = filter_client_kwargs(ctx.http_client, {
                "json": payload,
                "headers": headers or None,
                "timeout": params.timeout_seconds,
                "max_response_bytes": params.max_response_bytes,
            })
            response = await ctx.http_client.request("POST", params.url, **kwargs)
        except httpx.TimeoutException as exc:
            raise NodeExecutionError(
                f"GraphQL endpoint did not respond within {params.timeout_seconds}s.",
                code="HTTP_TIMEOUT", node_id=self.node_type, retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise NodeExecutionError(
                f"GraphQL request failed: {exc}",
                code="HTTP_REQUEST_FAILED", node_id=self.node_type, retryable=True,
            ) from exc

        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            code = (
                "HTTP_TIMEOUT" if response.status_code == 408
                else "HTTP_REQUEST_FAILED"
            )
            raise NodeExecutionError(
                f"GraphQL endpoint returned HTTP {response.status_code}.",
                code=code, node_id=self.node_type, retryable=retryable,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise NodeExecutionError(
                "GraphQL response was not valid JSON.",
                code="HTTP_REQUEST_FAILED", node_id=self.node_type, retryable=False,
            ) from exc

        errors = body.get("errors") or []
        if errors:
            first = errors[0]
            message = str(first.get("message", ""))[:300]
            raise NodeExecutionError(
                f"GraphQL error: {message}",
                code="GRAPHQL_ERROR", node_id=self.node_type, retryable=False,
            )

        data = body.get("data")
        return NodeResult(output_items=[{
            "data": data,
            "headers": dict(response.headers),
            "statusCode": response.status_code,
            "statusMessage": response.reason_phrase or ("OK" if 200 <= response.status_code < 300 else "Error"),
        }])
