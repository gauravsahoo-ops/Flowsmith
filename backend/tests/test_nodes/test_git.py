"""Tests for the Git node (read-only inspection of a user-supplied repository)."""

from __future__ import annotations

import shutil
import subprocess

import httpx
import pytest

from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.git import GitNode, GitParams, _validate_repo_path

_has_git = shutil.which("git") is not None


def _make_ctx():
    return NodeContext(
        execution_id="test",
        workflow_id="wf",
        logger=None,
        http_client=httpx.AsyncClient(),
    )


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


@pytest.mark.skipif(not _has_git, reason="git CLI not installed in environment")
@pytest.mark.asyncio
async def test_git_branches_lists_current(tmp_path):
    node = GitNode()
    repo = _make_repo(tmp_path)
    result = await node.run(
        _make_ctx(), GitParams(operation="branches", repo_path=str(repo)), []
    )
    assert result.output_items[0]["operation"] == "branches"
    assert result.output_items[0]["branches"]
    assert result.output_items[0]["current"]


@pytest.mark.skipif(not _has_git, reason="git CLI not installed in environment")
@pytest.mark.asyncio
async def test_git_log_returns_commits(tmp_path):
    node = GitNode()
    repo = _make_repo(tmp_path)
    result = await node.run(
        _make_ctx(), GitParams(operation="log", repo_path=str(repo), limit=3), []
    )
    commits = result.output_items[0]["commits"]
    assert 1 <= len(commits) <= 3
    assert set(commits[0]) == {"hash", "author", "date", "subject"}


@pytest.mark.skipif(not _has_git, reason="git CLI not installed in environment")
@pytest.mark.asyncio
async def test_git_status_shape(tmp_path):
    node = GitNode()
    repo = _make_repo(tmp_path)
    result = await node.run(
        _make_ctx(), GitParams(operation="status", repo_path=str(repo)), []
    )
    assert result.output_items[0]["operation"] == "status"
    assert "output" in result.output_items[0]


@pytest.mark.asyncio
async def test_git_bad_repo_fails_cleanly(tmp_path):
    node = GitNode()
    with pytest.raises(NodeExecutionError):
        await node.run(
            _make_ctx(),
            GitParams(operation="log", repo_path=str(tmp_path / "not-a-repo")),
            [],
        )


def test_git_blocks_application_source_tree():
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[2]
    with pytest.raises(NodeExecutionError) as exc:
        _validate_repo_path(str(backend_root))
    assert exc.value.code == "PATH_BLOCKED"


def test_git_registered():
    from app.nodes.registry import get

    assert get("git") is GitNode
