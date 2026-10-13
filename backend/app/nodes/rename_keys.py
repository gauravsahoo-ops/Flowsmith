"""Rename Keys node.

Rewrites field names on each item. This is a common "map the payload to what
the next connector expects" step, and without it users fall back to the code
node for what should be a one-line transform.

Renaming is order-sensitive: `{"a": "b", "b": "a"}` has to swap the two keys
rather than collapse them. The implementation therefore resolves every rename
against the *original* item and applies the result in one pass, so a chain like
`a -> b -> c` moves the value to `b`, not all the way to `c`. A rename whose
target already exists is reported in `collisions` instead of being applied
silently, because overwriting a field the user did not ask to touch is the sort
of data loss that is very hard to notice downstream.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

# Sentinel for "the source key was not on this item". Distinct from a key whose
# value happens to be None.
_MISSING = object()


class RenameKeysParams(BaseModel):
    renames: dict[str, str] = Field(
        default_factory=dict,
        description="Map of current field name to new field name.",
    )
    mode: Literal["rename", "copy", "remove"] = Field(
        default="rename",
        description=(
            "rename replaces the old field, copy keeps it alongside the new one, "
            "remove deletes the listed keys and ignores their values."
        ),
    )
    # Nested access uses a dotted path, e.g. "profile.name".
    use_paths: bool = Field(
        default=False,
        description="Treat the keys as dotted paths into nested objects.",
    )
    keep_unmatched: bool = Field(
        default=True,
        description="Pass items through untouched when none of the keys are present.",
    )


def _get_path(item: dict[str, Any], path: str) -> Any:
    """Resolve a dotted path. Returns _MISSING if any segment is absent."""
    current: Any = item
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _set_path(item: dict[str, Any], path: str, value: Any) -> None:
    """Write a dotted path, creating intermediate dicts as needed."""
    parts = path.split(".")
    current = item
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            current[part] = nxt
        current = nxt
    current[parts[-1]] = value


def _del_path(item: dict[str, Any], path: str) -> None:
    parts = path.split(".")
    current = item
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            return
        current = nxt
    current.pop(parts[-1], None)


@register
class RenameKeysNode(BaseNode[RenameKeysParams]):
    node_type = "rename_keys"
    display_name = "Rename Keys"
    version = 1
    description = "Rename, copy, or remove fields on the data passing through."
    category = "Transform"
    icon = "rename_keys"
    parameters_schema = RenameKeysParams
    # The three modes behave differently enough that `use_paths` only makes
    # sense for two of them, so the panel gates on the selected mode.
    operation_selector = "mode"
    operations: dict[str, dict[str, Any]] = {
        "rename": {
            "display_name": "Rename",
            "description": "Move each listed key to its new name.",
            # keep_unmatched only decides what happens to items that had none
            # of the source keys, which remove never branches on.
            "properties": ["renames", "use_paths", "keep_unmatched"],
            "required": ["renames"],
            "idempotency": "idempotent",
            "retryable": False,
            "output_preview": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Items with each listed key moved to its new name.",
            },
        },
        "copy": {
            "display_name": "Copy",
            "description": "Write each value to a new key, keeping the original.",
            "properties": ["renames", "use_paths", "keep_unmatched"],
            "required": ["renames"],
            "idempotency": "idempotent",
            "retryable": False,
            "output_preview": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Items carrying both the original and the copied key.",
            },
        },
        "remove": {
            "display_name": "Remove",
            "description": "Delete the listed keys; the mapping values are ignored.",
            "properties": ["renames", "use_paths"],
            "required": ["renames"],
            "idempotency": "idempotent",
            "retryable": False,
            "output_preview": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Items with the listed keys deleted.",
            },
        },
    }

    async def run(
        self,
        ctx: NodeContext,
        params: RenameKeysParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        # In remove mode the mapping values are irrelevant - only the keys
        # matter - so an entry like {"secret": ""} still has to be honoured.
        # Otherwise the non-empty-target filter would silently drop it.
        if params.mode == "remove":
            renames = {k: k for k in (params.renames or {}) if k}
        else:
            renames = {k: v for k, v in (params.renames or {}).items() if k and v}
        if not renames:
            return NodeResult(
                output_items=list(input_items),
                metadata={"touched_items": 0, "collisions": [], "renamed_fields": 0},
            )

        output_items: list[dict[str, Any]] = []
        collisions: list[dict[str, str]] = []
        # How many items actually had at least one of the source keys. Reporting
        # this is what makes "my rename did nothing" diagnosable at a glance.
        touched_items = 0

        for item in input_items:
            if not isinstance(item, dict):
                # The engine types items as objects, so a scalar is wrapped
                # rather than dropped. Losing it silently would be worse than
                # putting it somewhere the next node can still see it.
                output_items.append({"value": item})
                continue

            if params.mode == "remove":
                for key in renames:
                    if params.use_paths:
                        _del_path(item, key)
                    else:
                        item.pop(key, None)
                output_items.append(item)
                touched_items += 1
                continue

            # Resolve every source against the original item first, so a swap
            # or a chain behaves predictably rather than cascading.
            resolved: list[tuple[str, str, Any]] = []
            for old, new in renames.items():
                if params.use_paths:
                    value = _get_path(item, old)
                else:
                    value = item.get(old, _MISSING)
                if value is _MISSING:
                    continue
                resolved.append((old, new, value))

            if not resolved:
                if not params.keep_unmatched:
                    output_items.append({})
                else:
                    output_items.append(item)
                continue

            touched_items += 1

            if params.mode == "copy":
                result = dict(item)
                for _old, new, value in resolved:
                    # A copy never clobbers an existing field it did not create.
                    if params.use_paths:
                        if _get_path(result, new) is not _MISSING:
                            collisions.append({"source": new, "target": new})
                        _set_path(result, new, value)
                    elif new in result:
                        collisions.append({"source": new, "target": new})
                    else:
                        result[new] = value
                output_items.append(result)
                continue

            # rename: strip the old keys, then place the new ones.
            result = dict(item)
            for old, _new, _value in resolved:
                if params.use_paths:
                    _del_path(result, old)
                else:
                    result.pop(old, None)

            for _old, new, value in resolved:
                if params.use_paths:
                    # Record the collision, then still write. Renaming a onto
                    # an occupied key has to displace the old value: skipping
                    # the write would delete the source field (above) while
                    # keeping the target, losing the user's data outright.
                    if _get_path(result, new) is not _MISSING:
                        collisions.append({"source": new, "target": new})
                    _set_path(result, new, value)
                elif new in result:
                    collisions.append({"source": new, "target": new})
                    result[new] = value
                else:
                    result[new] = value

            output_items.append(result)

        # `touched_items` is what actually moved, which is what a user inspects
        # when a rename did not do what they expected.
        return NodeResult(
            output_items=output_items,
            metadata={
                "touched_items": touched_items,
                "collisions": collisions,
                "renamed_fields": len(renames),
            },
        )
