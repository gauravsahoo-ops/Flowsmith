"""Rename Keys node.

The cases worth pinning are the ones where a naive implementation is subtly
wrong rather than obviously broken: a swap collapsing onto one key, a rename
chain cascading further than the user asked, a rename clobbering an unrelated
field that happened to share the target name, and `keep_unmatched: False`
dropping fields the user never mentioned.
"""

from __future__ import annotations

import pytest

from app.engine.node_base import NodeContext
from app.nodes.registry import NODE_REGISTRY, _load_builtin_nodes
from app.nodes.rename_keys import RenameKeysNode

_load_builtin_nodes()


def _params(**kwargs):
    return RenameKeysNode.parameters_schema.model_validate(kwargs)


async def _run(params, items):
    return await RenameKeysNode().run(None, params, items)


def test_registered():
    assert "rename_keys" in NODE_REGISTRY


async def test_basic_rename():
    res = await _run(_params(renames={"first_name": "firstName"}), [{"first_name": "Ada"}])
    assert res.output_items == [{"firstName": "Ada"}]


async def test_rename_across_multiple_items():
    items = [{"a": 1}, {"a": 2}, {"b": 3}]
    res = await _run(_params(renames={"a": "z"}), items)
    assert res.output_items == [{"z": 1}, {"z": 2}, {"b": 3}]
    # Unmatched items pass through untouched by default.
    assert res.metadata["touched_items"] == 2


async def test_swap_does_not_collapse():
    """{'a': 'b', 'b': 'a'} must swap, not leave one winner."""
    res = await _run(_params(renames={"a": "b", "b": "a"}), [{"a": 1, "b": 2}])
    assert res.output_items == [{"a": 2, "b": 1}]


async def test_chain_does_not_cascade():
    """a -> b, b -> c moves a to b, not onward to c."""
    res = await _run(_params(renames={"a": "b", "b": "c"}), [{"a": 1, "b": 2}])
    # Both values relocate to their new names; neither travels twice.
    assert res.output_items == [{"b": 1, "c": 2}]


async def test_rename_to_an_occupied_key_is_reported_not_silently_lost():
    """A rename displaces the old value rather than being dropped.

    The source key is deleted before the target is written, so if the write
    were skipped the source value would vanish while the target kept its
    stale contents. The rename must win, with the collision surfaced.
    """
    res = await _run(_params(renames={"a": "b"}), [{"a": 1, "b": 2}])
    assert res.output_items[0]["b"] == 1
    assert "a" not in res.output_items[0]
    assert {"source": "b", "target": "b"} in res.metadata["collisions"]


async def test_copy_keeps_the_original():
    res = await _run(_params(renames={"a": "b"}, mode="copy"), [{"a": 1}])
    assert res.output_items == [{"a": 1, "b": 1}]


async def test_copy_does_not_clobber_an_existing_target():
    res = await _run(_params(renames={"a": "b"}, mode="copy"), [{"a": 1, "b": 9}])
    # The pre-existing b wins; the collision is surfaced rather than hidden.
    assert res.output_items[0]["b"] == 9
    assert res.metadata["collisions"]


async def test_remove_drops_the_listed_keys():
    res = await _run(_params(renames={"a": "", "b": ""}, mode="remove"), [{"a": 1, "b": 2, "c": 3}])
    assert res.output_items == [{"c": 3}]


async def test_nested_paths():
    res = await _run(
        _params(renames={"profile.name": "profile.full_name"}, use_paths=True),
        [{"profile": {"name": "Ada", "age": 36}}],
    )
    assert res.output_items == [{"profile": {"full_name": "Ada", "age": 36}}]


async def test_nested_missing_path_leaves_item_unchanged():
    item = {"profile": {"name": "Ada"}}
    res = await _run(
        _params(renames={"profile.missing": "x"}, use_paths=True), [item]
    )
    assert res.output_items == [{"profile": {"name": "Ada"}}]


async def test_create_intermediate_objects_on_nested_write():
    res = await _run(
        _params(renames={"a": "x.y.z"}, use_paths=True), [{"a": 1}]
    )
    assert res.output_items == [{"x": {"y": {"z": 1}}}]


async def test_keep_unmatched_false_blanks_items_with_no_match():
    res = await _run(
        _params(renames={"a": "b"}, keep_unmatched=False), [{"a": 1}, {"c": 3}]
    )
    assert res.output_items == [{"b": 1}, {}]


async def test_empty_renames_is_a_passthrough():
    items = [{"a": 1}]
    res = await _run(_params(renames={}), items)
    assert res.output_items == items
    assert res.metadata["renamed_fields"] == 0


async def test_rename_to_the_same_name_is_a_no_op_not_data_loss():
    res = await _run(_params(renames={"a": "a"}), [{"a": 1}])
    assert res.output_items == [{"a": 1}]


async def test_non_dict_items_are_wrapped_not_dropped():
    """The engine types items as objects, so scalars are preserved under a key."""
    res = await _run(_params(renames={"a": "b"}), [{"a": 1}, "string", 42])
    assert res.output_items == [{"b": 1}, {"value": "string"}, {"value": 42}]


async def test_none_values_are_preserved():
    """A key whose value is None must still be renamed, not treated as absent."""
    res = await _run(_params(renames={"a": "b"}), [{"a": None, "c": 1}])
    assert res.output_items == [{"b": None, "c": 1}]


async def test_multiple_renames_in_one_pass():
    res = await _run(
        _params(renames={"a": "x", "b": "y", "c": "z"}), [{"a": 1, "b": 2, "c": 3, "d": 4}]
    )
    assert res.output_items == [{"x": 1, "y": 2, "z": 3, "d": 4}]
    assert res.metadata["touched_items"] == 1


async def test_source_item_is_not_mutated_in_place():
    source = {"a": 1}
    await _run(_params(renames={"a": "b"}), [source])
    assert source == {"a": 1}, "the node must not mutate its input"


async def test_blank_or_empty_targets_are_ignored():
    """A mapping with an empty side would otherwise delete or duplicate keys."""
    res = await _run(_params(renames={"a": "", "": "b"}), [{"a": 1}])
    assert res.output_items == [{"a": 1}]
