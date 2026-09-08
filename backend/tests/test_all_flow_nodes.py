import pytest
import httpx
from app.nodes.registry import NODE_REGISTRY, _load_builtin_nodes
from app.engine.node_base import NodeContext
from app.engine.errors import NodeExecutionError
from app.nodes.condition_base import Condition

_load_builtin_nodes()

@pytest.fixture
def ctx():
    client = httpx.AsyncClient()
    return NodeContext(
        workflow_id="wf_test",
        execution_id="exec_test",
        node_id="node_test",
        logger=None,
        http_client=client,
    )

@pytest.mark.asyncio
async def test_execute_workflow_trigger_node(ctx):
    cls = NODE_REGISTRY["execute_workflow_trigger"]
    node = cls()
    res = await node.run(ctx, cls.parameters_schema(), [{"msg": "data from parent"}])
    assert res.output_items == [{"msg": "data from parent"}]

@pytest.mark.asyncio
async def test_filter_node(ctx):
    cls = NODE_REGISTRY["filter"]
    node = cls()
    # 1. Legacy condition test
    cond = Condition(left="$json.a", operator="equals", right=1)
    params = cls.parameters_schema(condition=cond)
    res = await node.run(ctx, params, [{"a": 1}, {"a": 2}])
    assert len(res.output_items) == 1
    assert res.output_items[0]["a"] == 1

    # 2. Multi-condition row format with 'is greater than' and 'is equal to'
    params2 = cls.parameters_schema.model_validate({
        "conditions": [
            {"left": "$json.score", "operator": "is greater than", "right": 50, "combinator": "AND"},
            {"left": "$json.status", "operator": "is equal to", "right": "active", "combinator": "AND"},
        ]
    })
    res2 = await node.run(ctx, params2, [
        {"score": 80, "status": "active"},
        {"score": 30, "status": "active"},
        {"score": 90, "status": "inactive"},
    ])
    assert len(res2.output_items) == 1
    assert res2.output_items[0]["score"] == 80

    # 3. String operator with ignoreCase option
    params3 = cls.parameters_schema.model_validate({
        "conditions": [
            {"left": "$json.name", "operator": "contains", "right": "JOHN"}
        ],
        "options": {"ignoreCase": True}
    })
    res3 = await node.run(ctx, params3, [
        {"name": "john doe"},
        {"name": "jane smith"}
    ])
    assert len(res3.output_items) == 1
    assert res3.output_items[0]["name"] == "john doe"

    # 4. Unary operator 'exists' and 'is empty'
    params4 = cls.parameters_schema.model_validate({
        "conditions": [
            {"left": "$json.email", "operator": "is not empty"}
        ]
    })
    res4 = await node.run(ctx, params4, [
        {"email": "test@example.com"},
        {"email": ""},
        {}
    ])
    assert len(res4.output_items) == 1
    assert res4.output_items[0]["email"] == "test@example.com"

@pytest.mark.asyncio
async def test_if_condition_node(ctx):
    cls = NODE_REGISTRY["if_condition"]
    node = cls()
    params = cls.parameters_schema.model_validate(
        {"condition": {"left": "$json.score", "operator": "greater_than", "right": 50}}
    )
    res = await node.run(ctx, params, [{"score": 80}])
    assert res.output_by_handle is not None
    assert len(res.output_by_handle["true"]) == 1

@pytest.mark.asyncio
async def test_loop_over_items_node(ctx):
    cls = NODE_REGISTRY["loop_over_items"]
    node = cls()
    params = cls.parameters_schema(field="items")
    res = await node.run(ctx, params, [{"items": [{"id": 1}, {"id": 2}]}])
    assert len(res.output_items) == 2

@pytest.mark.asyncio
async def test_merge_node(ctx):
    cls = NODE_REGISTRY["merge"]
    node = cls()
    params = cls.parameters_schema(mode="append")
    res = await node.run(ctx, params, [{"x": 1}, {"y": 2}])
    assert len(res.output_items) == 2

@pytest.mark.asyncio
async def test_compare_datasets_node(ctx):
    cls = NODE_REGISTRY["compare_datasets"]
    node = cls()
    params = cls.parameters_schema(
        input1=[{"id": 1, "name": "Alice"}],
        input2=[{"id": 1, "name": "Alice Modified"}]
    )
    res = await node.run(ctx, params, [])
    assert res.output_items is not None
    assert len(res.output_items) > 0

@pytest.mark.asyncio
async def test_sub_workflow_node(ctx):
    cls = NODE_REGISTRY["sub_workflow"]
    node = cls()
    assert node.node_type == "sub_workflow"
    assert node.category == "Flow"
    assert hasattr(node, "run")

@pytest.mark.asyncio
async def test_stop_and_error_node(ctx):
    cls = NODE_REGISTRY["stop_and_error"]
    node = cls()
    params = cls.parameters_schema(error_message="Controlled stop error")
    with pytest.raises(NodeExecutionError) as exc_info:
        await node.run(ctx, params, [{"item": 1}])
    assert "Controlled stop error" in str(exc_info.value)

@pytest.mark.asyncio
async def test_switch_node(ctx):
    cls = NODE_REGISTRY["switch"]
    node = cls()
    params = cls.parameters_schema(
        rules=[{"left": "$json.tier", "operator": "equals", "right": "vip", "output": "route_0"}]
    )
    res = await node.run(ctx, params, [{"tier": "vip"}])
    assert res.output_by_handle is not None
    assert len(res.output_by_handle["route_0"]) == 1

@pytest.mark.asyncio
async def test_wait_node(ctx):
    cls = NODE_REGISTRY["wait"]
    node = cls()
    params = cls.parameters_schema(mode="delay", seconds=0.01)
    res = await node.run(ctx, params, [{"status": "ok"}])
    assert res.output_items == [{"status": "ok"}]
