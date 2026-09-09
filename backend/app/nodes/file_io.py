"""File I/O node (spec 7).

Writes data to a file or reads from a file. Supports path templates using
`{{ }}` expressions that the executor resolves before run() is called.

Write mode creates/overwrites the file. Read mode returns the file content.

Uses async I/O (aiofiles) to avoid blocking the event loop. Path validation
is enforced even for template expressions — the resolved path is checked
after template resolution.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Literal

import aiofiles
from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class FileIOParams(BaseModel):
    path: str = Field(min_length=1, description="File system path.")
    mode: Literal["write", "append", "read"] = Field(
        default="write", description="File operation mode."
    )
    encoding: str = Field(default="utf-8", description="File encoding.")
    content: str = Field(
        default="", description="Content to write (ignored in read mode)."
    )
    create_parents: bool = Field(
        default=True, description="Create parent directories if they don't exist."
    )
    max_size_bytes: int = Field(
        default=50 * 1024 * 1024,
        ge=0,
        description="Max file size for read mode in bytes (0 = unlimited). 50 MB default.",
    )
    binary: bool = Field(
        default=False,
        description="Binary mode: read/write raw bytes and store in binary property.",
    )
    binary_property: str = Field(
        default="data",
        description="Binary property key name on item (e.g. 'data').",
    )


@register
class FileIONode(BaseNode[FileIOParams]):
    node_type = "file_io"
    display_name = "File I/O"
    version = 2
    description = "Read from or write to a file on disk with async I/O and binary storage."
    category = "Storage"
    icon = "📄"
    parameters_schema = FileIOParams
    credential_types = []

    # S11: Blocked paths for path traversal protection
    _BLOCKED_PREFIXES = (
        "/etc/", "/proc/", "/sys/", "/dev/", "/var/run/", "/boot/",
        "/root/", "/sbin/", "/bin/",
        "C:\\Windows\\", "C:\\Program Files\\", "C:\\ProgramData\\",
    )

    @classmethod
    def _validate_path(cls, path: str) -> None:
        """Block path traversal to sensitive system directories."""
        resolved = os.path.realpath(path)
        for prefix in cls._BLOCKED_PREFIXES:
            if resolved.lower().startswith(prefix.lower()):
                raise NodeExecutionError(
                    f"Access to '{resolved}' is blocked for security reasons.",
                    code="PATH_BLOCKED", node_id="file_io", retryable=False,
                )

    async def run(
        self,
        ctx: NodeContext,
        params: FileIOParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        from app.engine.binary_data import get_binary_data_buffer, prepare_binary_data

        resolved_path = params.path
        # S11: Path traversal protection — always validate the resolved path
        self._validate_path(resolved_path)

        # Ensure parent directories exist for write/append modes
        if params.mode in ("write", "append") and params.create_parents:
            parent = os.path.dirname(resolved_path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)

        if params.mode == "read":
            if not os.path.exists(resolved_path):
                raise NodeExecutionError(
                    f"File not found: {resolved_path}",
                    code="FILE_NOT_FOUND",
                    node_id=self.node_type,
                    retryable=False,
                )
            # Check file size before reading
            file_size = os.path.getsize(resolved_path)
            if params.max_size_bytes > 0 and file_size > params.max_size_bytes:
                raise NodeExecutionError(
                    f"File too large: {file_size} bytes exceeds limit of {params.max_size_bytes} bytes.",
                    code="FILE_TOO_LARGE",
                    node_id=self.node_type,
                    retryable=False,
                )
            if params.binary:
                async with aiofiles.open(resolved_path, "rb") as f:
                    raw = await f.read()
                filename = os.path.basename(resolved_path)
                binary_meta = prepare_binary_data(raw, file_name=filename)
                return NodeResult(output_items=[{
                    "json": {
                        "success": True,
                        "path": resolved_path,
                        "fileName": filename,
                        "size_bytes": file_size,
                    },
                    "binary": {
                        params.binary_property: binary_meta,
                    },
                }])
            else:
                async with aiofiles.open(resolved_path, "r", encoding=params.encoding) as f:
                    content = await f.read()
                return NodeResult(output_items=[{
                    "success": True,
                    "content": content,
                    "path": resolved_path,
                    "size_bytes": file_size,
                }])

        # Write or append mode
        if params.binary:
            mode = "wb" if params.mode == "write" else "ab"
            raw = b""
            # Check if input item contains binary data
            if input_items:
                first_item = input_items[0]
                bin_dict = first_item.get("binary") or {}
                bin_entry = bin_dict.get(params.binary_property)
                if bin_entry and isinstance(bin_entry, dict):
                    try:
                        raw = get_binary_data_buffer(bin_entry)
                    except Exception as e:
                        raise NodeExecutionError(
                            f"Failed to read binary input buffer: {e}",
                            code="BINARY_READ_ERROR",
                            node_id=self.node_type,
                            retryable=False,
                        ) from e
            if not raw and params.content:
                raw = base64.b64decode(params.content)

            async with aiofiles.open(resolved_path, mode) as f:
                await f.write(raw)
            bytes_written = len(raw)
        else:
            mode = "w" if params.mode == "write" else "a"
            async with aiofiles.open(resolved_path, mode, encoding=params.encoding) as f:
                await f.write(params.content)
            bytes_written = len(params.content.encode(params.encoding))

        return NodeResult(output_items=[{
            "success": True,
            "path": resolved_path,
            "bytes_written": bytes_written,
        }])
