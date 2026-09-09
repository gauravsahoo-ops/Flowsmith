"""HTML extract node.

Parse HTML with stdlib html.parser only and pull out text, links,
images, or a simple table. No network fetch here — pair with the
HTTP Request node for remote pages.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class HtmlExtractParams(BaseModel):
    operation: Literal["text", "links", "images", "tables"] = Field(default="text")
    html: str = Field(default="", description="HTML source (empty = first input item html/body).")
    max_items: int = Field(default=100, ge=1, le=2000)


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.images: list[str] = []
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._link: dict[str, str] | None = None
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k: (v or "") for k, v in attrs}
        if tag in ("script", "style"):
            self._skip = True
            return
        if tag == "a":
            self._link = {"href": attrs_d.get("href", ""), "text": ""}
        elif tag == "img" and attrs_d.get("src"):
            self.images.append(attrs_d["src"])
        elif tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False
        elif tag == "a" and self._link is not None:
            self.links.append(self._link)
            self._link = None
        elif tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._table is not None and self._row is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        chunk = data.strip()
        if chunk:
            self.text_parts.append(chunk)
        if self._link is not None:
            self._link["text"] += data
        if self._cell is not None:
            self._cell.append(data)


def _source(params: HtmlExtractParams, items: list[dict[str, Any]]) -> str:
    if params.html:
        return params.html
    if not items:
        return ""
    first = items[0] if isinstance(items[0], dict) else {}
    for key in ("html", "body", "content", "text"):
        if isinstance(first.get(key), str) and first[key]:
            return first[key]
    return str(first)


@register
class HtmlExtractNode(BaseNode[HtmlExtractParams]):
    node_type = "html_extract"
    display_name = "HTML Extract"
    version = 1
    description = "Extract text, links, images, or tables from HTML."
    category = "Transform"
    icon = "🔍"
    parameters_schema = HtmlExtractParams

    async def run(
        self,
        ctx: NodeContext,
        params: HtmlExtractParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        parser = _Collector()
        parser.feed(_source(params, input_items or "")[:500000])
        if params.operation == "links":
            return NodeResult(output_items=[{"href": l["href"], "text": l["text"].strip()} for l in parser.links[: params.max_items]])
        if params.operation == "images":
            return NodeResult(output_items=[{"src": s} for s in parser.images[: params.max_items]])
        if params.operation == "tables":
            tables = parser.tables[: params.max_items]
            return NodeResult(output_items=[{"table": t} for t in tables] or [{"table": []}])
        text = " ".join(parser.text_parts)
        return NodeResult(output_items=[{"text": text[:50000]}])
