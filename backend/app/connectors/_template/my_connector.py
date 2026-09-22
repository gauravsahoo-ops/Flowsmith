"""Reusable connector template — copy this directory to add a connector.

Three steps to ship a new integration (NO core-engine changes required):

1. Copy this folder to ``app/connectors/<your_connector>/`` and rename
   symbols (``MyConnectorConnector`` → your product).
2. Implement the seven lifecycle stages below (only ``execute`` is
   mandatory; every other stage has a working default).
3. Register it in ``app.connectors.register_builtin_connectors`` with
   ``build_my_connector_definition()`` and add credential type(s) to
   ``app.credentials.registry`` if you need stored secrets.

The engine routes your ``node_types`` automatically through
``ConnectorRegistry`` → ``op_execute``; discovery, retries, timeouts,
trace reporting and metrics come free.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorSDK,
    ConnectorCategory,
    ConnectorErrorCode,
    make_connector_error,
)
from app.security.safe_http_client import get_safe_http_client

# ----------------------------------------------------------------------
# 1) PARAMETERS — validated from the node's resolved payload
# ----------------------------------------------------------------------


class MyConnectorParams(BaseModel):
    operation: str = Field(default="fetch", description="Operation key.")
    resource_id: str = Field(default="", description="Target resource id.")
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


# ----------------------------------------------------------------------
# 2) CONNECTOR — lifecycle stages marked in order
# ----------------------------------------------------------------------


class MyConnectorConnector(ConnectorSDK):
    """TEMPLATE: rename class + connector_id/display_name/description."""

    connector_id = "my_connector"          # ← unique key
    display_name = "My Connector"
    description = "TEMPLATE connector — replace me."
    category = ConnectorCategory.API        # or WEBHOOK/SCHEDULE/TRANSFORM/LOGIC
    version = "1.0.0"

    # -- DISCOVER -------------------------------------------------------
    # Metadata below (node_types, version, ops declared in the paired
    # definition) is what GET /api/connectors exposes.

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)

    @property
    def node_types(self) -> list[str]:
        return ["my_connector"]          # ← unique node type

    # -- VALIDATE + CONFIGURE -------------------------------------------
    # connect(config) runs when a credential/config binds; raise/False to
    # reject bad configuration early.

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(config.get("api_key"))

    async def disconnect(self) -> None:
        self.status = __import__("app.connectors", fromlist=["ConnectorStatus"]).ConnectorStatus.DISCONNECTED

    # -- AUTHENTICATE ----------------------------------------------------
    # Resolve auth material for one call. Prefer CredentialResolver data
    # arriving in context["credentials"]["my_connector"].

    def _auth_headers(self, context: dict[str, Any] | None) -> dict[str, str]:
        creds = (context or {}).get("credentials", {}).get("my_connector", {})
        api_key = str(creds.get("api_key") or "").strip()
        if not api_key:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "My Connector needs an 'my_connector' credential with api_key.",
                retryable=False,
            )
        return {"Authorization": f"Bearer {api_key}"}

    # -- EXECUTE ----------------------------------------------------------
    # Dispatch table style keeps operations small and independently
    # testable. Raise make_connector_error(...) for typed failures.

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = MyConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid My Connector payload: {exc}",
                retryable=False,
            ) from exc

        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()

        headers = self._auth_headers(context)
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    "GET",
                    f"https://api.example.com/v1/{params.resource_id}",
                    headers=headers,
                    timeout=params.timeout_seconds,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE,
                f"My Connector unreachable: {exc}",
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            code = (
                ConnectorErrorCode.NOT_FOUND
                if response.status_code == 404
                else ConnectorErrorCode.UNAVAILABLE
                if response.status_code >= 500
                else ConnectorErrorCode.BAD_REQUEST
            )
            raise make_connector_error(
                code,
                f"My Connector fetch failed ({response.status_code}).",
                retryable=response.status_code >= 500 or response.status_code == 429,
            )

        # -- NORMALIZE --------------------------------------------------
        raw = response.json()
        return self.normalize_output(op, payload, raw)

    # -- NORMALIZE (override) ---------------------------------------------
    # Single place to shape provider wire data into your canonical form.

    def normalize_output(self, operation: str, payload: dict[str, Any], output: Any) -> Any:
        if isinstance(output, dict):
            return {**output, "normalized": True}
        return output

    # -- REPORT ------------------------------------------------------------
    # Reporting (events/trace/metrics) is handled by the execution engine;
    # nodes only emit domain events via ctx.emit_event when relevant.
