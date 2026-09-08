"""Split node — matches n8n Split Out (Item Lists).

Splits an array into individual items for downstream per-item processing.
Supports:
  - Fields To Split Out (fieldToSplitOut / field)
  - Include options:
      * No Other Fields (noOtherFields)
      * All Other Fields (allOtherFields)
      * Selected Other Fields (selectedOtherFields) + fieldsToInclude
  - Options:
      * Destination Field Name (destinationFieldName)
      * Disable Dot Notation (disableDotNotation)
      * Include Binary (includeBinary)
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class SplitOptions(BaseModel):
    model_config = ConfigDict(extra="allow")

    destinationFieldName: str = Field(default="", description="Field name to place each split element into.")
    disableDotNotation: bool = Field(default=False, description="Treat dots in field names as literal keys.")
    includeBinary: bool = Field(default=False, description="Include $binary data from the parent item.")


class SplitParams(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    fieldToSplitOut: str = Field(
        default="",
        description="The field containing the array to split out (e.g. data or items).",
        alias="field",
    )
    include: str = Field(
        default="noOtherFields",
        description="Which fields from the input item to include: noOtherFields, allOtherFields, or selectedOtherFields.",
    )
    fieldsToInclude: list[str] = Field(
        default_factory=list,
        description="Fields from parent item to include when include='selectedOtherFields'.",
    )
    options: SplitOptions = Field(default_factory=SplitOptions)
    batch_size: int = Field(default=0, ge=0, description="Max items to emit (0 = unlimited)")

    @model_validator(mode="before")
    @classmethod
    def _normalize_params(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)

        # Normalize field name
        for k in ("fieldsToSplitOut", "field_to_split_out", "field"):
            if k in d and not d.get("fieldToSplitOut"):
                d["fieldToSplitOut"] = d[k]

        # Normalize include values
        inc = d.get("include")
        if isinstance(inc, str):
            inc_lower = inc.lower().replace(" ", "").replace("_", "")
            if "all" in inc_lower:
                d["include"] = "allOtherFields"
            elif "selected" in inc_lower:
                d["include"] = "selectedOtherFields"
            elif "no" in inc_lower:
                d["include"] = "noOtherFields"

        # Normalize fieldsToInclude
        if "fieldsToInclude" in d:
            val = d["fieldsToInclude"]
            if isinstance(val, str):
                d["fieldsToInclude"] = [f.strip() for f in val.split(",") if f.strip()]
            elif isinstance(val, list):
                # Flatten any dicts or nested objects: [{'field': 'name'}] -> ['name']
                cleaned = []
                for item in val:
                    if isinstance(item, dict):
                        cleaned.append(item.get("field") or item.get("name") or str(item))
                    elif isinstance(item, str) and item.strip():
                        cleaned.append(item.strip())
                d["fieldsToInclude"] = cleaned

        # Normalize options dict
        if "options" in d and isinstance(d["options"], dict):
            opts = dict(d["options"])
            if "destination_field_name" in opts and "destinationFieldName" not in opts:
                opts["destinationFieldName"] = opts["destination_field_name"]
            if "disable_dot_notation" in opts and "disableDotNotation" not in opts:
                opts["disableDotNotation"] = opts["disable_dot_notation"]
            if "include_binary" in opts and "includeBinary" not in opts:
                opts["includeBinary"] = opts["include_binary"]
            d["options"] = opts

        return d


@register
class SplitNode(BaseNode[SplitParams]):
    node_type = "split"
    display_name = "Split Out"
    version = 1
    description = "Turn a list inside item(s) into separate items"
    category = "Flow"
    icon = "split_out"
    parameters_schema = SplitParams

    async def run(
        self,
        ctx: NodeContext,
        params: SplitParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        output_items: list[dict[str, Any]] = []
        field_name = getattr(params, "fieldToSplitOut", None) or getattr(params, "field", None) or ""
        raw_options = getattr(params, "options", None) or SplitOptions()
        options = SplitOptions(**raw_options) if isinstance(raw_options, dict) else raw_options
        dest_field = (getattr(options, "destinationFieldName", "") or "").strip()
        disable_dots = bool(getattr(options, "disableDotNotation", False))
        include_mode = getattr(params, "include", "noOtherFields") or "noOtherFields"
        include_binary = bool(getattr(options, "includeBinary", False))

        for item in input_items:
            if not isinstance(item, dict):
                output_items.append({"value": item})
                continue

            # Resolve the array/target to split
            if field_name:
                if disable_dots:
                    target = item.get(field_name)
                else:
                    target = _resolve_field(item, field_name)
            else:
                target = item

            # Normalize target to list of elements
            if isinstance(target, list):
                elements = target
            elif isinstance(target, dict):
                elements = [target]
            elif target is not None:
                elements = [target]
            else:
                elements = []

            # Determine fields to inherit from parent item
            parent_extras: dict[str, Any] = {}
            if include_mode == "allOtherFields":
                # Exclude the field that was split out to avoid duplicating large arrays
                root_key = field_name.split(".")[0] if "." in field_name and not disable_dots else field_name
                parent_extras = {k: v for k, v in item.items() if k != root_key}
            elif include_mode == "selectedOtherFields":
                for sel in params.fieldsToInclude:
                    if sel in item:
                        parent_extras[sel] = item[sel]
                    elif not disable_dots and "." in sel:
                        val = _resolve_field(item, sel)
                        if val is not None:
                            parent_extras[sel] = val

            if include_binary and "$binary" in item and "$binary" not in parent_extras:
                parent_extras["$binary"] = item["$binary"]

            for elem in elements:
                out_item: dict[str, Any] = {}

                # 1. Base element placement
                if dest_field:
                    out_item[dest_field] = elem
                elif isinstance(elem, dict):
                    out_item = dict(elem)
                else:
                    # If fieldToSplitOut is a simple name, use it or 'value'
                    key = field_name.split(".")[-1] if field_name and not disable_dots else (field_name or "value")
                    out_item[key] = elem

                # 2. Merge parent extras (parent fields accompany the split item)
                merged = {**parent_extras, **out_item}
                output_items.append(merged)

                if params.batch_size > 0 and len(output_items) >= params.batch_size:
                    break

            if params.batch_size > 0 and len(output_items) >= params.batch_size:
                output_items = output_items[: params.batch_size]
                break

        always_output = bool(getattr(options, "alwaysOutputData", False) or getattr(options, "always_output_data", False))
        if not output_items and always_output:
            output_items = [{}]

        return NodeResult(output_items=output_items)


def _resolve_field(item: dict[str, Any], field: str) -> Any:
    """Resolve a dot-separated field path against a dict."""
    if not field:
        return item
    parts = field.split(".")
    current: Any = item
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


@register
class SplitOutNode(BaseNode[SplitParams]):
    node_type = "split_out"
    display_name = "Split Out"
    version = 1
    description = "Turn a list inside item(s) into separate items"
    category = "Flow"
    icon = "split_out"
    parameters_schema = SplitParams
    _delegate = SplitNode()

    async def run(
        self,
        ctx: NodeContext,
        params: SplitParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        return await self._delegate.run(ctx, params, input_items)

