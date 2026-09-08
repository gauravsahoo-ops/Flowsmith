"""Shopify connector implementing the ConnectorSDK interface.

Thin mapper over ShopifyProviderClient; credentials arrive via
context["credentials"]["shopify"].
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
from app.providers.shopify import ShopifyProviderClient


class ShopifyConnectorParams(BaseModel):
    operation: str = Field(default="list_products", description="get_product | list_products | create_product | get_order.")
    product_id: str = ""
    order_id: str = ""
    title: str = ""
    body_html: str = ""
    vendor: str = ""
    tags: list[str] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=250)
    max_pages: int = Field(default=3, ge=1, le=10)
    status: str = "active"
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class ShopifyConnector(ConnectorSDK):
    connector_id = "shopify"
    display_name = "Shopify"
    description = "Manage products and orders in a Shopify store."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = ShopifyProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["shopify"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(
            str(config.get("shop_domain") or "").strip()
            and str(config.get("access_token") or "").strip()
        )

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
            params = ShopifyConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Shopify payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("shopify") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()

        try:
            if op == "get_product":
                return await self._provider.get_product(
                    creds, str(raw.get("product_id") or params.product_id),
                    timeout=params.timeout_seconds,
                )
            if op == "list_products":
                status = str(raw.get("status") or params.status)
                if status not in ("active", "archived", "draft"):
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST,
                        "status must be active|archived|draft.",
                        retryable=False,
                    )
                return await self._provider.list_products(
                    creds, limit=params.limit, max_pages=params.max_pages,
                    status=status, timeout=params.timeout_seconds,
                )
            if op == "create_product":
                tags_raw = raw.get("tags")
                tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else params.tags
                return await self._provider.create_product(
                    creds, str(raw.get("title") or params.title),
                    body_html=str(raw.get("body_html") or params.body_html),
                    vendor=str(raw.get("vendor") or params.vendor),
                    tags=tags or None, timeout=params.timeout_seconds,
                )
            if op == "get_order":
                return await self._provider.get_order(
                    creds, str(raw.get("order_id") or params.order_id),
                    timeout=params.timeout_seconds,
                )
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported Shopify operation '{operation}'.", retryable=False,
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
