"""Git node (Flow).

Read-only Git repository inspection via the local git CLI: working-tree
status, recent commit log, and branch list. Write operations (clone,
commit, push) are deliberately out of scope — use the Code node or CI
for mutations.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class GitParams(BaseModel):
    operation: Literal["status", "log", "branches"] = Field(
        default="status", description="status: working tree state; log: recent commits; branches: local branches.",
    )
    repo_path: str = Field(default=".", description="Path to the repository working tree.")
    limit: int = Field(default=10, ge=1, le=100, description="Max commits/refs to return (log mode).")


async def _git(repo_path: str, *args: str, timeout: float = 30.0) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", repo_path or ".", *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        from app.engine.errors import NodeExecutionError

        raise NodeExecutionError("Git CLI is not installed on system.", code="GIT_NOT_FOUND", node_id="", retryable=False)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        from app.engine.errors import NodeExecutionError

        raise NodeExecutionError("Git command timed out.", code="GIT_TIMEOUT", node_id="", retryable=True)
    if proc.returncode != 0:
        from app.engine.errors import NodeExecutionError

        raise NodeExecutionError(
            f"Git failed ({' '.join(args)}): {err.decode(errors='replace')[:300]}",
            code="GIT_FAILED", node_id="", retryable=False,
        )
    return out.decode(errors="replace")


def _validate_repo_path(path: str) -> None:
    """Containment allowlist: working directory, configured file root, temp."""
    import os
    import tempfile
    from pathlib import Path

    from app.engine.errors import NodeExecutionError
    from app.nodes.file_io import FileIONode

    resolved = os.path.realpath(path)
    for prefix in FileIONode._BLOCKED_PREFIXES:
        if resolved.lower().startswith(prefix.lower()):
            raise NodeExecutionError(
                f"Access to '{resolved}' is blocked for security reasons.",
                code="PATH_BLOCKED", node_id="git", retryable=False,
            )
    roots = {Path.cwd().resolve(), Path(tempfile.gettempdir()).resolve()}
    roots.update(Path(r) for r in FileIONode._allowed_roots())
    resolved_path = Path(resolved)
    for root in roots:
        if resolved_path.is_relative_to(root):
            return
    raise NodeExecutionError(
        f"Access to '{resolved}' is blocked for security reasons. "
        f"Git operations are restricted to the working directory, the file root, and temp.",
        code="PATH_BLOCKED", node_id="git", retryable=False,
    )


@register
class GitNode(BaseNode[GitParams]):
    node_type = "git"
    display_name = "Git"
    version = 1
    description = "Read-only Git inspection: status, log, branches"
    category = "Flow"
    icon = "git"
    parameters_schema = GitParams
    input_handles = ["main"]
    output_handles = ["main"]

    async def run(
        self,
        ctx: NodeContext,
        params: GitParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        op = (params.operation or "status").lower()
        repo = params.repo_path or "."
        _validate_repo_path(repo)
        if op == "status":
            out = await _git(repo, "status", "--short", "--branch")
            return NodeResult(output_items=[{"operation": "status", "output": out}])
        if op == "log":
            out = await _git(repo, "log", f"-{max(1, min(params.limit, 100))}", "--pretty=format:%H|%an|%ad|%s", "--date=short")
            commits = [
                dict(zip(("hash", "author", "date", "subject"), line.split("|", 3)))
                for line in out.splitlines() if line.strip()
            ]
            return NodeResult(output_items=[{"operation": "log", "commits": commits}])
        if op == "branches":
            out = await _git(repo, "branch", "--list")
            branches = [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]
            current = next((b for b in out.splitlines() if b.startswith("*")), "").strip("* ")
            return NodeResult(output_items=[{"operation": "branches", "current": current, "branches": branches}])
        from app.engine.errors import NodeExecutionError

        raise NodeExecutionError(f"Unsupported Git operation '{params.operation}'.", code="GIT_BAD_OPERATION", node_id="", retryable=False)
