"""Tests for the Human Approval node."""

import pytest
import httpx
from unittest.mock import MagicMock, patch
from app.nodes.human_approval import HumanApprovalNode, HumanApprovalParams
from app.engine.node_base import NodeContext, MemoryKVStore


def _make_ctx():
    return NodeContext(
        execution_id="test_exec",
        workflow_id="wf",
        node_id="approval_node",
        logger=None,
        http_client=httpx.AsyncClient(),
        storage=MemoryKVStore(),
    )


@pytest.mark.asyncio
async def test_human_approval_initial():
    """First run: returns waiting_approval status."""
    node = HumanApprovalNode()
    ctx = _make_ctx()
    params = HumanApprovalParams(message="Approve this?")
    items = [{"data": "test"}]

    with patch("app.db.get_session") as mock_session:
        mock_db = MagicMock()
        mock_session.return_value = mock_db
        mock_execution = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_execution

        result = await node.run(ctx, params, items)
        assert result.output_items == []
        assert result.metadata.get("waiting_approval") is True
        assert result.metadata.get("message") == "Approve this?"


@pytest.mark.asyncio
async def test_human_approval_resumed():
    """Resumed execution: returns input items with approval metadata."""
    node = HumanApprovalNode()
    ctx = _make_ctx()
    await ctx.storage.set("_approval_data", {"approved": True, "approved_by": 1})
    params = HumanApprovalParams()
    items = [{"data": "test"}]

    result = await node.run(ctx, params, items)
    assert len(result.output_items) == 1
    assert result.output_items[0] == {"data": "test"}
    assert result.metadata.get("approved") is True


def test_human_approval_params():
    """Test parameter schema."""
    params = HumanApprovalParams(
        message="Please approve",
        approvers=[1, 2, 3],
        timeout_hours=48,
    )
    assert params.message == "Please approve"
    assert params.approvers == [1, 2, 3]
    assert params.timeout_hours == 48
