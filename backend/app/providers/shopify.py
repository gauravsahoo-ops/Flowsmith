"""Shopify Admin API provider client (Phase 11 business connectors).

Admin access token auth (``shpat_…``) against
``https://{shop}.myshopify.com/admin/api/2024-10``.

Pagination: Shopify uses RFC-5988 ``Link`` headers carrying opaque
``page_info`` cursors — ``list_products`` walks the ``rel="next"`` link.
Rate limits: REST returns 429 + ``Retry-After`` when the leaky bucket is
empty; mapped to RATE_LIMITED with the delay attached.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.connectors import ConnectorErrorCode, make_connector_error
from app.providers.base import json_error_message
from app.security.safe_http_client import get_safe_http_client

SHOPIFY_API_VERSION = "2024-10"
_SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
_extract_shopify_error = json_error_message("errors", "message")
_ID_RE = re.compile(r"^\d+$")


def _require_creds(creds: dict) -> tuple[str, str]:
    shop = str((creds or {}).get("shop_domain") or "").strip().lower().replace("https://", "").rstrip("/")
    token = str(creds.get("access_token") or "").strip()
    if not shop or not token:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "Shopify connector needs a 'shopify' credential with shop_domain and access_token.",
            retryable=False,
        )
    if not _SHOP_RE.match(shop):
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "shop_domain must be your store's myshopify.com domain, e.g. acme.myshopify.com.",
            retryable=False,
        )
    return shop, token


def _api_base(creds: dict) -> str:
    shop, _ = _require_creds(creds)
    return f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}"


def next_link(response: httpx.Response) -> str | None:
    """Extract the ``rel="next"`` target from a Link header."""
    header = response.headers.get("Link") or ""
    for part in header.split(","):
        segment = part.strip()
        match = re.match(r'^<([^>]+)>;\s*rel="([a-z]+)"$', segment)
        if match and match.group(2) == "next":
            return match.group(1)
    return None


class ShopifyProviderClient:
    """Low-level Shopify Admin REST client."""

    async def request_shopify(
        self, creds: dict, method: str, path: str, *,
        json_body: dict | None = None, params: dict | None = None,
        url_override: str = "",
        timeout: float = 30.0, what: str = "request",
    ) -> httpx.Response:
        _, token = _require_creds(creds)
        url = url_override or f"{_api_base(creds)}{path}"
        try:
            async with get_safe_http_client() as client:
                response = await client.request(
                    method, url, json=json_body or None, params=params or None,
                    headers={
                        "X-Shopify-Access-Token": token,
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                    },
                    timeout=timeout,
                )
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"Shopify unreachable: {exc}", retryable=True,
            ) from exc
        if response.status_code == 429:
            delay = response.headers.get("Retry-After")
            raise make_connector_error(
                ConnectorErrorCode.RATE_LIMITED,
                "Shopify rate limit hit (leaky bucket empty).",
                retryable=True,
                retry_after=float(delay) if delay else None,
            )
        if response.status_code >= 400:
            code_map = {401: ConnectorErrorCode.AUTH_FAILED, 403: ConnectorErrorCode.FORBIDDEN,
                        404: ConnectorErrorCode.NOT_FOUND, 422: ConnectorErrorCode.BAD_REQUEST}
            code = code_map.get(
                response.status_code,
                ConnectorErrorCode.UNAVAILABLE if response.status_code >= 500 else ConnectorErrorCode.BAD_REQUEST,
            )
            raise make_connector_error(
                code,
                f"Shopify {what} failed ({response.status_code}). {_extract_shopify_error(response)}".strip(),
                retryable=response.status_code >= 500,
            )
        return response

    async def get_product(self, creds: dict, product_id: str, timeout: float = 30.0) -> dict:
        pid = str(product_id or "").strip()
        if not _ID_RE.match(pid):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "A numeric product id is required.", retryable=False)
        response = await self.request_shopify(
            creds, "GET", f"/products/{pid}.json", timeout=timeout, what="get product",
        )
        product = response.json().get("product") or {}
        return self._product_summary(product)

    @staticmethod
    def _product_summary(product: dict) -> dict:
        return {
            "id": product.get("id"),
            "title": product.get("title"),
            "status": product.get("status"),
            "handle": product.get("handle"),
            "variants": [
                {"id": v.get("id"), "sku": v.get("sku"), "price": v.get("price")}
                for v in (product.get("variants") or [])
            ],
        }

    async def list_products(self, creds: dict, limit: int = 50, max_pages: int = 3,
                            status: str = "active", timeout: float = 30.0) -> dict:
        limit = min(max(int(limit or 50), 1), 250)
        max_pages = min(max(int(max_pages or 1), 1), 10)
        products: list[dict] = []
        params: dict[str, Any] = {"limit": limit, "status": status}
        url = ""
        for _ in range(max_pages):
            response = await self.request_shopify(
                creds, "GET", "/products.json",
                params=params if not url else None,
                url_override=url,
                timeout=timeout, what="list products",
            )
            data = response.json()
            products.extend(self._product_summary(p) for p in data.get("products", []))
            url = next_link(response) or ""
            if not url:
                break
        return {"products": products, "count": len(products)}

    async def create_product(self, creds: dict, title: str, body_html: str = "",
                             vendor: str = "", tags: list[str] | None = None,
                             timeout: float = 30.0) -> dict:
        title_clean = str(title or "").strip()
        if not title_clean:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "create_product requires a title.", retryable=False)
        payload: dict[str, Any] = {"title": title_clean}
        if body_html:
            payload["body_html"] = body_html
        if vendor:
            payload["vendor"] = vendor
        if tags:
            payload["tags"] = ", ".join(str(t) for t in tags)
        response = await self.request_shopify(
            creds, "POST", "/products.json", json_body={"product": payload},
            timeout=timeout, what="create product",
        )
        product = response.json().get("product") or {}
        out = self._product_summary(product)
        out["success"] = True
        return out

    async def get_order(self, creds: dict, order_id: str, timeout: float = 30.0) -> dict:
        oid = str(order_id or "").strip()
        if not _ID_RE.match(oid):
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "A numeric order id is required.", retryable=False)
        response = await self.request_shopify(
            creds, "GET", f"/orders/{oid}.json",
            params={"fields": "id,name,email,total_price,financial_status,fulfillment_status,line_items,created_at"},
            timeout=timeout, what="get order",
        )
        order = response.json().get("order") or {}
        return {
            "id": order.get("id"),
            "name": order.get("name"),
            "email": order.get("email"),
            "total_price": order.get("total_price"),
            "financial_status": order.get("financial_status"),
            "fulfillment_status": order.get("fulfillment_status"),
            "line_items_count": len(order.get("line_items") or []),
        }
