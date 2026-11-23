"""Application users must never be able to read the source tree."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.config import get_settings
from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.file_io import FileIONode, FileIOParams
from app.nodes.git import _validate_repo_path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _ctx() -> NodeContext:
    return NodeContext(
        execution_id="source-protection",
        workflow_id="wf",
        logger=None,
        http_client=httpx.AsyncClient(),
    )


def test_file_io_blocks_backend_source():
    target = BACKEND_ROOT / "app" / "main.py"
    with pytest.raises(NodeExecutionError) as exc:
        FileIONode._validate_path(str(target))
    assert exc.value.code == "PATH_BLOCKED"


def test_file_io_blocks_source_through_traversal():
    target = BACKEND_ROOT / "data" / "files" / ".." / ".." / "app" / "main.py"
    with pytest.raises(NodeExecutionError) as exc:
        FileIONode._validate_path(str(target))
    assert exc.value.code == "PATH_BLOCKED"


@pytest.mark.asyncio
async def test_file_io_read_of_source_is_blocked():
    node = FileIONode()
    target = BACKEND_ROOT / "app" / "main.py"
    with pytest.raises(NodeExecutionError):
        await node.run(
            _ctx(),
            FileIOParams(path=str(target), mode="read"),
            [],
        )


def test_file_io_default_root_is_the_data_directory():
    roots = FileIONode._allowed_roots()
    assert (BACKEND_ROOT / "data" / "files").resolve() in roots
    assert Path.cwd().resolve() not in roots


def test_file_io_rejects_source_tree_as_configured_root(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "file_io_root", str(BACKEND_ROOT))
    with pytest.raises(NodeExecutionError) as exc:
        FileIONode._allowed_roots()
    assert exc.value.code == "UNSAFE_FILE_ROOT"


def test_file_io_rejects_repository_root_as_configured_root(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "file_io_root", str(BACKEND_ROOT.parent))
    with pytest.raises(NodeExecutionError) as exc:
        FileIONode._allowed_roots()
    assert exc.value.code == "UNSAFE_FILE_ROOT"


def test_file_io_allows_temp_files(tmp_path):
    target = tmp_path / "allowed.txt"
    target.write_text("ok", encoding="utf-8")
    FileIONode._validate_path(str(target))


def test_git_blocks_backend_source_tree():
    with pytest.raises(NodeExecutionError) as exc:
        _validate_repo_path(str(BACKEND_ROOT))
    assert exc.value.code == "PATH_BLOCKED"
