"""Merge node (Phase 8).

Combines items arriving from multiple parent branches into a single
output stream.  The engine's DAG fan-in already collects items from
all parents into ``input_items`` (see ``_gather_input`` in the
executor); this node applies an explicit merge *strategy* over those
items.

Strategies
~~~~~~~~~~
- ``concat`` (default): all items flattened into one output list.
- ``keep_first``: discard all but the first item — useful when only
  one upstream result matters (e.g. a cached value or single-row query).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class MergeParams(BaseModel):
    strategy: Literal["concat", "keep_first"] = Field(
        default="concat",
        description=(
            "How to combine items from multiple input branches. "
            "'concat': flatten all into one list. "
            "'keep_first': only the first item survives."
        ),
    )


@register
class MergeNode(BaseNode[MergeParams]):
    node_type = "merge"
    display_name = "Merge"
    version = 1
    description = "Merges data of multiple streams once data from both is available"
    category = "Flow"
    icon = "merge"
    parameters_schema = MergeParams

    async def run(
        self,
        ctx: NodeContext,
        params: MergeParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        if params.strategy == "keep_first":
            output = input_items[:1] if input_items else []
        else:
            output = input_items

        ctx.emit_event(
            "merge.completed",
            node_id=ctx.node_id,
            strategy=params.strategy,
            input_count=len(input_items),
            output_count=len(output),
        )
        return NodeResult(output_items=output)
