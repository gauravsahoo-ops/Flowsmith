"""IF / Condition node tests (spec 51.3).

The IF node evaluates `$json.path` conditions natively, per item.
`{{ }}` expressions are resolved by the executor before run() (spec
8.5), so multi-item per-item behavior is tested with `$json.` paths.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.if_condition import IfConditionNode, IfConditionParams


async def _run(condition: dict, items: list[dict]):
    node = IfConditionNode()
    params = IfConditionParams.model_validate({"condition": condition})
    ctx = NodeContext(
        execution_id="exec_1", workflow_id="wf_1",
        logger=logging.getLogger("test"), http_client=httpx.AsyncClient(),
    )
    return await node.run(ctx, params, items)


@pytest.mark.parametrize(
    "condition,items,true_count,false_count",
    [
        ({"left": "$json.subject", "operator": "contains", "right": "urgent"},
         [{"subject": "URGENT: fix"}, {"subject": "weekly"}, {"subject": "urgent!"}], 1, 2),
        ({"left": "$json.age", "operator": "greater_than", "right": 18},
         [{"age": 21}, {"age": 15}], 1, 1),
        ({"left": "$json.email", "operator": "equals", "right": "a@b.com"},
         [{"email": "a@b.com"}, {"email": "c@d.com"}], 1, 1),
        ({"left": "$json.email", "operator": "not_equals", "right": "a@b.com"},
         [{"email": "a@b.com"}, {"email": "c@d.com"}], 1, 1),
        ({"left": "$json.name", "operator": "starts_with", "right": "Al"},
         [{"name": "Alice"}, {"name": "Bob"}], 1, 1),
        ({"left": "$json.missing", "operator": "exists", "right": None},
         [{"x": 1}, {"missing": "yes"}], 1, 1),
        ({"left": "$json.score", "operator": "less_than", "right": 10},
         [{"score": 3}, {"score": 42}], 1, 1),
    ],
)
async def test_operators(condition, items, true_count, false_count):
    result = await _run(condition, items)
    assert len(_true(result)) == true_count
    assert len(_false(result)) == false_count


async def test_literal_condition():
    result = await _run({"left": "value", "operator": "equals", "right": "value"}, [{}])
    assert len(_true(result)) == 1


async def test_boolean_coercion():
    result = await _run({"left": "$json.done", "operator": "equals", "right": "true"}, [{"done": True}])
    assert len(_true(result)) == 1


async def test_invalid_comparison_raises():
    with pytest.raises(NodeExecutionError) as exc:
        await _run({"left": "$json.age", "operator": "greater_than", "right": "abc"}, [{"age": "old"}])
    assert exc.value.code == "INVALID_CONDITION"


async def test_nested_json_path():
    result = await _run(
        {"left": "$json.user.role", "operator": "equals", "right": "admin"},
        [{"user": {"role": "admin"}}, {"user": {"role": "user"}}],
    )
    assert len(_true(result)) == 1
    assert len(_false(result)) == 1


async def test_empty_left_value_does_not_crash_validation():
    # When user adds condition but hasn't typed in left yet, it evaluates safely without crashing
    result = await _run({"left": "", "operator": "is equal to", "right": "something"}, [{}])
    assert len(_false(result)) == 1


def _true(result) -> list[dict]:
    return _handle(result, "true")


def _false(result) -> list[dict]:
    return _handle(result, "false")


def _handle(result, handle: str) -> list[dict]:
    assert result.output_by_handle is not None
    return result.output_by_handle[handle]
