"""FTP node (Flow).

Browse and move small text files on FTP/FTPS servers (list, download,
upload, delete, mkdir) using an `ftp` credential. Blocking ftplib calls
run in a worker thread so the event loop never stalls. Binary and large
files belong in the File I/O node.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from app.providers.ftp import DEFAULT_MAX_BYTES, FtpSession


class FtpParams(BaseModel):
    operation: Literal["list", "download_text", "upload_text", "delete", "mkdir"] = Field(
        default="list", description="FTP operation to run.",
    )
    path: str = Field(default="", description="Remote path (file or directory).")
    content: str = Field(default="", description="Text content for upload_text.")
    limit: int = Field(default=100, ge=1, le=1000, description="Max entries for list.")
    max_bytes: int = Field(default=DEFAULT_MAX_BYTES, ge=1024, le=10 * 1024 * 1024,
                            description="Text download cap in bytes.")


@register
class FtpNode(BaseNode[FtpParams]):
    node_type = "ftp"
    display_name = "FTP"
    version = 1
    description = "List, download, upload, and delete files on FTP/FTPS servers"
    category = "Flow"
    icon = "ftp"
    parameters_schema = FtpParams
    credential_types = ["ftp"]
    input_handles = ["main"]
    output_handles = ["main"]

    async def run(
        self,
        ctx: NodeContext,
        params: FtpParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        creds = (ctx.credentials or {}).get("ftp") or {}
        if not creds:
            raise NodeExecutionError(
                "This node needs an FTP credential (host, username, password).",
                code="CREDENTIALS_REQUIRED", node_id="ftp", retryable=False,
            )
        op = (params.operation or "list").lower()
        path = params.path or ""
        if op == "list":
            with FtpSession(creds) as session:
                entries = await asyncio.to_thread(session.list, path, params.limit)
            return NodeResult(output_items=[{"operation": "list", "path": path, "entries": entries}])
        if op == "download_text":
            with FtpSession(creds) as session:
                text = await asyncio.to_thread(session.download_text, path, params.max_bytes)
            return NodeResult(output_items=[{"operation": "download_text", "path": path, "content": text}])
        if op == "upload_text":
            with FtpSession(creds) as session:
                result = await asyncio.to_thread(session.upload_text, path, params.content)
            return NodeResult(output_items=[{"operation": "upload_text", **result}])
        if op == "delete":
            with FtpSession(creds) as session:
                result = await asyncio.to_thread(session.delete, path)
            return NodeResult(output_items=[{"operation": "delete", **result}])
        if op == "mkdir":
            with FtpSession(creds) as session:
                result = await asyncio.to_thread(session.mkdir, path)
            return NodeResult(output_items=[{"operation": "mkdir", **result}])
        raise NodeExecutionError(f"Unsupported FTP operation '{params.operation}'.",
                                 code="FTP_BAD_OPERATION", node_id="", retryable=False)
