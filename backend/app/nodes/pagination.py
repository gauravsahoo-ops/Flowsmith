"""Pagination node (Phase 8).

Splits a list of input items into pages of a configurable size.
Each page is emitted as a separate output item with metadata about
its position in the overall result set.

Use cases:

- Processing large result sets in batches (e.g. 1000 database rows
  processed 100 at a time).
- Rate-limiting downstream API calls by controlling batch sizes.
- Respecting upstream pagination limits (e.g. ``max_pages`` on the
  HTTP Request node).

Parameters
~~~~~~~~~~
- ``page_size``: items per page (1-1000, default 100).
- ``field``: optional dot-path to a list field within each input item
  that contains the data to page.  When set, each input item is
  inspected; the list at ``field`` is paged independently and the
  surrounding item fields are preserved.

Output
~~~~~~
Each output item has:

- ``data``: the list of items for this page.
- ``page_index``: 0-based page number.
- ``total_pages``: total number of pages in the result set.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class PaginationParams(BaseModel):
    page_size: int = Field(default=100, ge=1, le=1000, description="Items per page")
    field: str = Field(
        default="",
        description="Dot-path to list field (empty = treat each input item as an element of the list to page)",
    )


@register
class PaginationNode(BaseNode[PaginationParams]):
    node_type = "pagination"
    display_name = "Pagination"
    version = 1
    description = "Split items into pages of a configurable size with page metadata."
    category = "Logic"
    icon = "pagination"
    parameters_schema = PaginationParams
    idempotency = "idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: PaginationParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        data = self._collect(input_items, params.field)
        if not data:
            data = [{}]

        total_pages = max(1, -(-len(data) // params.page_size))  # ceil division
        pages: list[dict[str, Any]] = []

        for page_idx in range(total_pages):
            start = page_idx * params.page_size
            chunk = data[start : start + params.page_size]
            pages.append({
                "data": chunk,
                "page_index": page_idx,
                "total_pages": total_pages,
                "page_size": params.page_size,
                "item_count": len(chunk),
            })

        ctx.emit_event(
            "pagination.completed",
            node_id=ctx.node_id,
            total_items=len(data),
            total_pages=total_pages,
            page_size=params.page_size,
        )
        return NodeResult(output_items=pages)

    @staticmethod
    def _collect(items: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
        """Extract data to page.  When ``field`` is set, each input
        item's list at that path is paged independently."""
        if not field:
            return list(items)

        result: list[dict[str, Any]] = []
        for item in items:
            value: Any = item
            for part in field.split("."):
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            if isinstance(value, list):
                result.extend(
                    v if isinstance(v, dict) else {"value": v} for v in value
                )
            elif value is not None:
                result.append(item)
        return result
