"""RSS feed node (original implementation).

Fetch an RSS/Atom feed over the execution HTTP client (so workflow
test-mode mocks apply) and emit one item per entry: title, link,
description, published. Response size is capped; only http/https URLs
are accepted. Pair with the Schedule trigger for polling.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from defusedxml.ElementTree import fromstring as _safe_fromstring
from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult, filter_client_kwargs
from app.nodes.registry import register

MAX_BYTES = 1_000_000


class RssFeedParams(BaseModel):
    url: str = Field(default="", description="RSS/Atom feed URL (http/https).")
    limit: int = Field(default=20, ge=1, le=200)
    timeout_seconds: float = Field(default=20.0, ge=1, le=120)


def _text(entry: Any, names: list[str]) -> str:
    for name in names:
        child = entry.find(name)
        if child is not None and child.text and child.text.strip():
            return child.text.strip()
    return ""


@register
class RssFeedNode(BaseNode[RssFeedParams]):
    node_type = "rss_feed"
    display_name = "RSS Feed"
    version = 1
    description = "Fetch an RSS/Atom feed into items."
    category = "Actions"
    icon = "rss_feed"
    parameters_schema = RssFeedParams
    idempotency = "idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: RssFeedParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        url = params.url.strip()
        scheme = urlparse(url).scheme.lower()
        if scheme not in ("http", "https") or not urlparse(url).netloc:
            raise NodeExecutionError(
                "A valid http/https feed URL is required.",
                code="RSS_BAD_URL", node_id="rss_feed", retryable=False,
            )
        try:
            kwargs = filter_client_kwargs(ctx.http_client, {"timeout": params.timeout_seconds})
            response = await ctx.http_client.get(url, **kwargs)
        except Exception as exc:
            raise NodeExecutionError(
                f"Feed fetch failed: {exc}",
                code="RSS_FETCH_ERROR", node_id="rss_feed", retryable=True,
            ) from exc
        if response.status_code >= 400:
            raise NodeExecutionError(
                f"Feed returned HTTP {response.status_code}.",
                code="RSS_HTTP_ERROR", node_id="rss_feed",
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        body = response.content[:MAX_BYTES] if isinstance(response.content, bytes) else str(response.text or "").encode()[:MAX_BYTES]
        try:
            root = _safe_fromstring(body)
        except Exception as exc:
            raise NodeExecutionError(
                "Feed XML could not be parsed.",
                code="RSS_PARSE_ERROR", node_id="rss_feed", retryable=False,
            ) from exc
        tag = root.tag.lower()
        entries: list[Any] = []
        if tag.endswith("rss") or root.find("channel") is not None:
            channel = root.find("channel")
            entries = channel.findall("item") if channel is not None else []
        elif tag.endswith("feed"):
            ns = "{http://www.w3.org/2005/Atom}"
            entries = root.findall(f"{ns}entry") or root.findall("entry")
        items: list[dict[str, Any]] = []
        for entry in entries[: params.limit]:
            link = _text(entry, ["link"])
            href = entry.find("{http://www.w3.org/2005/Atom}link")
            if href is not None and href.get("href"):
                link = href.get("href", "")
            items.append({
                "title": _text(entry, ["title"]),
                "link": link,
                "description": _text(entry, ["description", "summary", "{http://www.w3.org/2005/Atom}summary"]),
                "published": _text(entry, ["pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published"]),
            })
        return NodeResult(output_items=items or [{"empty": True}])
