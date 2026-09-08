"""Compare Datasets node (Flow).

Compares two sets of items (Input A and Input B) to identify:
- Added items (present in B but not in A)
- Removed items (present in A but not in B)
- Modified items (present in both with differing values)
- Same items (identical in both)
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class CompareDatasetsParams(BaseModel):
    model_config = ConfigDict(extra="allow")

    merge_by: Literal["all_fields", "key_fields"] = Field(
        default="all_fields",
        description="Whether to match items by specific key fields or all fields.",
    )
    key_fields: list[str] = Field(
        default_factory=list,
        description="Key fields to match items between datasets (e.g. ['id'] or ['email']).",
    )
    fields_to_compare: list[str] = Field(
        default_factory=list,
        description="Optional list of fields to compare. If empty, all fields are compared.",
    )
    input1: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Direct dataset 1 items",
    )
    input2: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Direct dataset 2 items",
    )


def _item_key(item: dict[str, Any], keys: list[str]) -> str:
    if keys:
        return json.dumps({k: item.get(k) for k in keys}, sort_keys=True)
    return json.dumps(item, sort_keys=True)


@register
class CompareDatasetsNode(BaseNode[CompareDatasetsParams]):
    node_type = "compare_datasets"
    display_name = "Compare Datasets"
    version = 1
    description = "Compare two inputs for changes"
    category = "Flow"
    icon = "compare_datasets"
    parameters_schema = CompareDatasetsParams
    input_handles = ["input_a", "input_b", "main"]
    output_handles = ["main", "different", "same"]

    async def run(
        self,
        ctx: NodeContext,
        params: CompareDatasetsParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        # Partition inputs into Dataset A and Dataset B
        # Items can be tagged with _dataset, _input, or _input_handle
        dataset_a: list[dict[str, Any]] = list(getattr(params, "input1", []) or [])
        dataset_b: list[dict[str, Any]] = list(getattr(params, "input2", []) or [])

        if not dataset_a and not dataset_b:
            for item in input_items:
                source = item.get("_dataset") or item.get("_input") or item.get("_input_handle") or ""
                source_str = str(source).lower()
                if "b" in source_str or "2" in source_str or "new" in source_str:
                    dataset_b.append(item)
                elif "a" in source_str or "1" in source_str or "old" in source_str:
                    dataset_a.append(item)
                else:
                    # If no tag, split evenly or treat first half as A, second half as B
                    if len(input_items) > 1 and len(dataset_a) < len(input_items) // 2:
                        dataset_a.append(item)
                    else:
                        dataset_b.append(item)

        keys = params.key_fields if params.merge_by == "key_fields" else []

        map_a = {_item_key(item, keys): item for item in dataset_a}
        map_b = {_item_key(item, keys): item for item in dataset_b}

        different_items: list[dict[str, Any]] = []
        same_items: list[dict[str, Any]] = []

        # Find same and modified/removed
        for k, item_a in map_a.items():
            if k in map_b:
                item_b = map_b[k]
                # Compare fields
                compare_keys = params.fields_to_compare or list(set(item_a.keys()) | set(item_b.keys()))
                diffs = {
                    field: {"from": item_a.get(field), "to": item_b.get(field)}
                    for field in compare_keys
                    if item_a.get(field) != item_b.get(field)
                }
                if diffs:
                    different_items.append({
                        **item_b,
                        "_status": "modified",
                        "_differences": diffs,
                    })
                else:
                    same_items.append({
                        **item_a,
                        "_status": "same",
                    })
            else:
                different_items.append({
                    **item_a,
                    "_status": "removed",
                })

        # Find added (in B but not in A)
        for k, item_b in map_b.items():
            if k not in map_a:
                different_items.append({
                    **item_b,
                    "_status": "added",
                })

        all_items = different_items + same_items

        return NodeResult(
            output_items=all_items,
            output_by_handle={
                "main": all_items,
                "different": different_items,
                "same": same_items,
            },
            metadata={
                "added_count": sum(1 for i in different_items if i.get("_status") == "added"),
                "removed_count": sum(1 for i in different_items if i.get("_status") == "removed"),
                "modified_count": sum(1 for i in different_items if i.get("_status") == "modified"),
                "same_count": len(same_items),
            },
        )
