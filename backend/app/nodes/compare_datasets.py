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


class MatchFieldPair(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    fieldA: str = ""
    fieldB: str = ""


class CompareDatasetsParams(BaseModel):
    model_config = ConfigDict(extra="allow")

    # n8n-parity fields
    fieldsToMatch: list[MatchFieldPair | dict[str, Any]] = Field(
        default_factory=list,
        description="List of field pairs to match items between Input A and Input B.",
    )
    whenThereAreDifferences: Literal["includeBoth", "useA", "useB", "useMix"] = Field(
        default="includeBoth",
        description="Which version of the data to output when differences are found.",
    )
    fuzzyCompare: bool = Field(
        default=False,
        description="Whether to tolerate small type differences (e.g. 3 and '3').",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional settings: fieldsToSkip, disableDotNotation, multipleMatches.",
    )

    # Legacy fields (backward compatibility)
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


def _values_equal(val_a: Any, val_b: Any, fuzzy: bool = False) -> bool:
    if val_a == val_b:
        return True
    if fuzzy:
        if val_a is None or val_b is None:
            return val_a == val_b
        # Numeric / string fuzzy match
        return str(val_a).strip() == str(val_b).strip()
    return False


def _match_key(item: dict[str, Any], field_names: list[str], fuzzy: bool = False) -> str:
    parts = []
    for f in field_names:
        v = item.get(f)
        if fuzzy and v is not None:
            parts.append(str(v).strip())
        else:
            parts.append(json.dumps(v, sort_keys=True) if v is not None else "null")
    return "|".join(parts)


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
                    if len(input_items) > 1 and len(dataset_a) < len(input_items) // 2:
                        dataset_a.append(item)
                    else:
                        dataset_b.append(item)

        # Parse match pairs
        match_pairs: list[tuple[str, str]] = []
        if params.fieldsToMatch:
            for m in params.fieldsToMatch:
                f_a = getattr(m, "fieldA", None) or (m.get("fieldA") if isinstance(m, dict) else "")
                f_b = getattr(m, "fieldB", None) or (m.get("fieldB") if isinstance(m, dict) else "")
                if f_a or f_b:
                    match_pairs.append((f_a or f_b, f_b or f_a))
        elif params.merge_by == "key_fields" and params.key_fields:
            for k in params.key_fields:
                match_pairs.append((k, k))

        fields_a = [p[0] for p in match_pairs]
        fields_b = [p[1] for p in match_pairs]

        fuzzy = params.fuzzyCompare
        options = params.options or {}
        skip_fields = set()
        if options.get("fieldsToSkip"):
            skip_fields = {s.strip() for s in str(options["fieldsToSkip"]).split(",") if s.strip()}

        map_a: dict[str, dict[str, Any]] = {}
        for item in dataset_a:
            k = _match_key(item, fields_a, fuzzy) if fields_a else json.dumps(item, sort_keys=True)
            map_a[k] = item

        map_b: dict[str, dict[str, Any]] = {}
        for item in dataset_b:
            k = _match_key(item, fields_b, fuzzy) if fields_b else json.dumps(item, sort_keys=True)
            map_b[k] = item

        different_items: list[dict[str, Any]] = []
        same_items: list[dict[str, Any]] = []

        # Compare items present in A
        for k, item_a in map_a.items():
            if k in map_b:
                item_b = map_b[k]
                compare_keys = [
                    f for f in (set(item_a.keys()) | set(item_b.keys()))
                    if f not in skip_fields and not f.startswith("_")
                ]
                diffs = {}
                for f in compare_keys:
                    va = item_a.get(f)
                    vb = item_b.get(f)
                    if not _values_equal(va, vb, fuzzy):
                        diffs[f] = {"from": va, "to": vb}

                if diffs:
                    if params.whenThereAreDifferences == "useA":
                        merged = {**item_a, "_status": "modified", "_differences": diffs}
                    elif params.whenThereAreDifferences == "useB":
                        merged = {**item_b, "_status": "modified", "_differences": diffs}
                    elif params.whenThereAreDifferences == "useMix":
                        merged = {**item_a, **item_b, "_status": "modified", "_differences": diffs}
                    else:  # includeBoth
                        merged = {
                            "inputA": item_a,
                            "inputB": item_b,
                            "_status": "modified",
                            "_differences": diffs,
                        }
                    different_items.append(merged)
                else:
                    same_items.append({**item_a, "_status": "same"})
            else:
                different_items.append({**item_a, "_status": "removed"})

        # Identify items in B but not in A (added)
        for k, item_b in map_b.items():
            if k not in map_a:
                different_items.append({**item_b, "_status": "added"})

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
