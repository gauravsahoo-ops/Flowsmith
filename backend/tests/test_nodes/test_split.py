import logging
import httpx
import pytest

from app.engine.node_base import NodeContext
from app.nodes.split import SplitNode, SplitParams


async def _run_split(params_dict: dict, input_items: list[dict]):
    node = SplitNode()
    params = SplitParams.model_validate(params_dict)
    ctx = NodeContext(
        execution_id="exec_test",
        workflow_id="wf_test",
        logger=logging.getLogger("test"),
        http_client=httpx.AsyncClient(),
    )
    res = await node.run(ctx, params, input_items)
    return res.output_items


@pytest.mark.asyncio
async def test_split_no_other_fields():
    data = [
        {
            "id": 100,
            "title": "Batch A",
            "items": [{"name": "Item 1"}, {"name": "Item 2"}],
        }
    ]
    out = await _run_split({"fieldToSplitOut": "items", "include": "noOtherFields"}, data)
    assert len(out) == 2
    assert out[0] == {"name": "Item 1"}
    assert out[1] == {"name": "Item 2"}
    assert "id" not in out[0]


@pytest.mark.asyncio
async def test_split_all_other_fields():
    data = [
        {
            "userId": "user_123",
            "company": "Acme",
            "records": [{"amount": 50}, {"amount": 75}],
        }
    ]
    out = await _run_split({"fieldToSplitOut": "records", "include": "allOtherFields"}, data)
    assert len(out) == 2
    assert out[0] == {"userId": "user_123", "company": "Acme", "amount": 50}
    assert out[1] == {"userId": "user_123", "company": "Acme", "amount": 75}


@pytest.mark.asyncio
async def test_split_selected_other_fields():
    data = [
        {
            "userId": "user_123",
            "secret": "hide_me",
            "tenant": "tenant_abc",
            "items": [{"val": 1}, {"val": 2}],
        }
    ]
    out = await _run_split({
        "fieldToSplitOut": "items",
        "include": "selectedOtherFields",
        "fieldsToInclude": ["userId", "tenant"],
    }, data)
    assert len(out) == 2
    assert out[0] == {"userId": "user_123", "tenant": "tenant_abc", "val": 1}
    assert "secret" not in out[0]


@pytest.mark.asyncio
async def test_split_destination_field_name():
    data = [
        {
            "orderId": 456,
            "tags": ["alpha", "beta"],
        }
    ]
    out = await _run_split({
        "fieldToSplitOut": "tags",
        "include": "allOtherFields",
        "options": {"destinationFieldName": "myTag"},
    }, data)
    assert len(out) == 2
    assert out[0] == {"orderId": 456, "myTag": "alpha"}
    assert out[1] == {"orderId": 456, "myTag": "beta"}


@pytest.mark.asyncio
async def test_split_primitives_without_destination():
    data = [{"nums": [10, 20]}]
    out = await _run_split({"fieldToSplitOut": "nums", "include": "noOtherFields"}, data)
    assert len(out) == 2
    assert out[0] == {"nums": 10}
    assert out[1] == {"nums": 20}
