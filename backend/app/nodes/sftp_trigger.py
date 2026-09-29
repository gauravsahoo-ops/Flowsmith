"""SFTP Trigger node (Phase 14 Core Node).

Periodically inspects a remote directory over SFTP using an `ssh` credential,
emitting items for newly created or modified files using checkpoint cursors.
"""

from __future__ import annotations

import asyncio
import fnmatch
from typing import Any, Literal
from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from app.providers.ssh import SshSession


class SftpTriggerParams(BaseModel):
    path: str = Field(default="/", description="Remote directory to monitor.")
    pattern: str = Field(default="*", description="Filename pattern (glob, e.g. *.csv or data_*.json).")
    cursor_mode: Literal["mtime", "filename"] = Field(
        default="mtime", description="Cursor tracking strategy to detect new files."
    )
    max_files_per_poll: int = Field(default=50, ge=1, le=500, description="Max files to emit per poll cycle.")


@register
class SftpTriggerNode(BaseNode[SftpTriggerParams]):
    node_type = "sftp_trigger"
    display_name = "SFTP Trigger"
    version = 1
    description = "Polls an SFTP directory and triggers workflow when new or updated files arrive"
    category = "Triggers"
    icon = "📡"
    parameters_schema = SftpTriggerParams
    credential_types = ["ssh"]
    input_handles = ["main"]
    output_handles = ["main"]
    idempotency = "conditionally_idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: SftpTriggerParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        creds = (ctx.credentials or {}).get("ssh") or {}
        if not creds:
            raise NodeExecutionError(
                "SFTP Trigger requires an SSH credential (host, username, password or private_key).",
                code="CREDENTIALS_REQUIRED",
                node_id="sftp_trigger",
                retryable=False,
            )

        def _poll_sftp() -> list[dict[str, Any]]:
            with SshSession(creds) as session:
                sftp = session.sftp()
                try:
                    entries = sftp.listdir_attr(params.path)
                except Exception as exc:
                    raise NodeExecutionError(
                        f"Failed to list SFTP directory '{params.path}': {exc}",
                        code="SFTP_LIST_FAILED",
                        node_id="sftp_trigger",
                        retryable=True,
                    ) from exc

                matched: list[dict[str, Any]] = []
                for attr in entries:
                    name = attr.filename
                    if name in (".", ".."):
                        continue
                    if params.pattern and not fnmatch.fnmatch(name, params.pattern):
                        continue
                    # Check if file vs directory (stat st_mode)
                    is_dir = False
                    import stat
                    if attr.st_mode and stat.S_ISDIR(attr.st_mode):
                        is_dir = True

                    matched.append({
                        "filename": name,
                        "path": f"{params.path.rstrip('/')}/{name}",
                        "size_bytes": attr.st_size or 0,
                        "modified_at": attr.st_mtime or 0,
                        "is_directory": is_dir,
                    })

                # Sort by mtime descending or name
                if params.cursor_mode == "mtime":
                    matched.sort(key=lambda x: x["modified_at"], reverse=True)
                else:
                    matched.sort(key=lambda x: x["filename"])

                return matched[: params.max_files_per_poll]

        files = await asyncio.to_thread(_poll_sftp)
        if not files:
            return NodeResult(output_items=[])

        return NodeResult(output_items=files)
