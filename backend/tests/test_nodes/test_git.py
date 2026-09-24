"""Tests for the Git node (read-only inspection of the repo itself)."""

import shutil
import pytest
import httpx
from app.nodes.git import GitNode, GitParams
from app.engine.node_base import NodeContext

_has_git = shutil.which("git") is not None


def _make_ctx():
    return NodeContext(
        execution_id="test",
        workflow_id="wf",
        logger=None,
        http_client=httpx.AsyncClient(),
    )


@pytest.mark.skipif(not _has_git, reason="git CLI not installed in environment")
@pytest.mark.asyncio
async def test_git_branches_lists_current():
    node = GitNode()
    result = await node.run(_make_ctx(), GitParams(operation="branches", repo_path="."), [])
    assert result.output_items[0]["operation"] == "branches"
    assert result.output_items[0]["branches"]
    assert result.output_items[0]["current"]


@pytest.mark.skipif(not _has_git, reason="git CLI not installed in environment")
@pytest.mark.asyncio
async def test_git_log_returns_commits():
    node = GitNode()
    result = await node.run(
        _make_ctx(), GitParams(operation="log", repo_path=".", limit=3), [])
    commits = result.output_items[0]["commits"]
    assert 1 <= len(commits) <= 3
    assert set(commits[0]) == {"hash", "author", "date", "subject"}


@pytest.mark.skipif(not _has_git, reason="git CLI not installed in environment")
@pytest.mark.asyncio
async def test_git_status_shape():
    node = GitNode()
    result = await node.run(_make_ctx(), GitParams(operation="status", repo_path="."), [])
    assert result.output_items[0]["operation"] == "status"
    assert "output" in result.output_items[0]


@pytest.mark.asyncio
async def test_git_bad_repo_fails_cleanly():
    from app.engine.errors import NodeExecutionError

    node = GitNode()
    with pytest.raises(NodeExecutionError):
        await node.run(
            _make_ctx(),
            GitParams(operation="log", repo_path="/nonexistent-xyz-123"), [])


def test_git_registered():
    from app.nodes.registry import get

    assert get("git") is GitNode
