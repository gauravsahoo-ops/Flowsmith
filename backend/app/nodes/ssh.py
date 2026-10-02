"""SSH node (Flow).

Run remote commands and move small text files over SSH/SFTP using an
`ssh` credential (password or private key). Blocking paramiko calls run
in a worker thread so the event loop never stalls.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from app.providers.ssh import DEFAULT_MAX_BYTES, SshSession


class SshParams(BaseModel):
    operation: Literal["exec", "sftp_download_text", "sftp_upload_text"] = Field(
        default="exec", description="SSH operation to run.",
    )
    command: str = Field(default="", description="Shell command for exec.")
    path: str = Field(default="", description="Remote path for SFTP operations.")
    content: str = Field(default="", description="Text content for sftp_upload_text.")
    timeout_seconds: float = Field(default=30.0, ge=1, le=600, description="Command timeout in seconds.")
    max_bytes: int = Field(default=DEFAULT_MAX_BYTES, ge=1024, le=10 * 1024 * 1024,
                            description="Text download cap in bytes.")


@register
class SshNode(BaseNode[SshParams]):
    node_type = "ssh"
    display_name = "SSH"
    version = 1
    description = "Run remote commands and move files over SSH/SFTP"
    category = "Flow"
    icon = "ssh"
    parameters_schema = SshParams
    credential_types = ["ssh"]
    input_handles = ["main"]
    output_handles = ["main"]

    async def run(
        self,
        ctx: NodeContext,
        params: SshParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        creds = (ctx.credentials or {}).get("ssh") or {}
        if not creds:
            raise NodeExecutionError(
                "This node needs an SSH credential (host, username, password or key).",
                code="CREDENTIALS_REQUIRED", node_id="ssh", retryable=False,
            )
        op = (params.operation or "exec").lower()
        if op == "exec":
            with SshSession(creds) as session:
                result = await asyncio.to_thread(session.exec, params.command, params.timeout_seconds)
            return NodeResult(output_items=[{"operation": "exec", **result}])
        if op == "sftp_download_text":
            with SshSession(creds) as session:
                text = await asyncio.to_thread(session.download_text, params.path, params.max_bytes)
            return NodeResult(output_items=[{"operation": "sftp_download_text", "path": params.path, "content": text}])
        if op == "sftp_upload_text":
            with SshSession(creds) as session:
                result = await asyncio.to_thread(session.upload_text, params.path, params.content)
            return NodeResult(output_items=[{"operation": "sftp_upload_text", **result}])
        raise NodeExecutionError(f"Unsupported SSH operation '{params.operation}'.",
                                 code="SSH_BAD_OPERATION", node_id="", retryable=False)
