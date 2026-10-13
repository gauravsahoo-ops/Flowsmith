"""Compression and archive node.

Provides standard library compression and archive utilities:
Zip, Unzip, Gzip, Gunzip, Tar, and Untar with Base64 encoding.
Operates on text, JSON, and binary file representations safely.
"""

from __future__ import annotations

import base64
import gzip
import io
import tarfile
import zipfile
from typing import Any, List, Literal

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class CompressionParams(BaseModel):
    operation: Literal["zip", "unzip", "gzip", "gunzip", "tar", "untar"] = Field(
        default="zip",
        description="Compression operation to perform.",
    )
    source_field: str = Field(
        default="data",
        description="Field containing text, base64 data, or filename to process.",
    )
    archive_name: str = Field(
        default="archive.zip",
        description="Output archive filename.",
    )
    file_name: str = Field(
        default="file.txt",
        description="Internal filename when archiving single items.",
    )


@register
class CompressionNode(BaseNode[CompressionParams]):
    node_type = "compression"
    display_name = "Compression"
    version = 1
    description = "Compress and decompress Zip, Gzip, and Tar archives."
    category = "Transform"
    icon = "folder"
    parameters_schema = CompressionParams

    async def run(
        self,
        ctx: NodeContext,
        params: CompressionParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        if not input_items:
            return NodeResult(output_items=[])

        try:
            if params.operation == "gzip":
                first = input_items[0]
                raw_data = first.get(params.source_field) or first.get("text") or str(first)
                data_bytes = raw_data.encode("utf-8") if isinstance(raw_data, str) else bytes(raw_data)
                compressed = gzip.compress(data_bytes)
                return NodeResult(output_items=[{
                    "filename": f"{params.file_name}.gz",
                    "base64": base64.b64encode(compressed).decode("ascii"),
                    "size_bytes": len(compressed),
                    "original_size": len(data_bytes),
                }])

            elif params.operation == "gunzip":
                first = input_items[0]
                raw_b64 = first.get(params.source_field) or first.get("base64") or ""
                compressed_bytes = base64.b64decode(raw_b64.strip())
                decompressed = gzip.decompress(compressed_bytes)
                try:
                    text_out = decompressed.decode("utf-8")
                except UnicodeDecodeError:
                    text_out = base64.b64encode(decompressed).decode("ascii")
                return NodeResult(output_items=[{
                    "text": text_out,
                    "size_bytes": len(decompressed),
                }])

            elif params.operation == "zip":
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for idx, item in enumerate(input_items):
                        content = item.get(params.source_field) or item.get("content") or item.get("text") or str(item)
                        fname = item.get("filename") or f"{params.file_name}_{idx + 1}.txt"
                        content_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)
                        zf.writestr(fname, content_bytes)
                buf.seek(0)
                zip_bytes = buf.getvalue()
                return NodeResult(output_items=[{
                    "filename": params.archive_name,
                    "base64": base64.b64encode(zip_bytes).decode("ascii"),
                    "file_count": len(input_items),
                    "size_bytes": len(zip_bytes),
                }])

            elif params.operation == "unzip":
                first = input_items[0]
                raw_b64 = first.get(params.source_field) or first.get("base64") or ""
                zip_bytes = base64.b64decode(raw_b64.strip())
                buf = io.BytesIO(zip_bytes)
                extracted_items: List[dict[str, Any]] = []
                with zipfile.ZipFile(buf, "r") as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        with zf.open(info.filename) as f:
                            raw = f.read()
                            try:
                                text_content = raw.decode("utf-8")
                            except UnicodeDecodeError:
                                text_content = base64.b64encode(raw).decode("ascii")
                            extracted_items.append({
                                "filename": info.filename,
                                "content": text_content,
                                "file_size": info.file_size,
                            })
                return NodeResult(output_items=extracted_items)

            elif params.operation == "tar":
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w:gz") as tf:
                    for idx, item in enumerate(input_items):
                        content = item.get(params.source_field) or item.get("content") or str(item)
                        fname = item.get("filename") or f"{params.file_name}_{idx + 1}.txt"
                        content_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)
                        tinfo = tarfile.TarInfo(name=fname)
                        tinfo.size = len(content_bytes)
                        tf.addfile(tinfo, io.BytesIO(content_bytes))
                buf.seek(0)
                tar_bytes = buf.getvalue()
                return NodeResult(output_items=[{
                    "filename": f"{params.archive_name}.tar.gz",
                    "base64": base64.b64encode(tar_bytes).decode("ascii"),
                    "file_count": len(input_items),
                    "size_bytes": len(tar_bytes),
                }])

            elif params.operation == "untar":
                first = input_items[0]
                raw_b64 = first.get(params.source_field) or first.get("base64") or ""
                tar_bytes = base64.b64decode(raw_b64.strip())
                buf = io.BytesIO(tar_bytes)
                extracted_items = []
                with tarfile.open(fileobj=buf, mode="r:*") as tf:
                    for member in tf.getmembers():
                        if not member.isfile():
                            continue
                        f = tf.extractfile(member)
                        if f:
                            raw = f.read()
                            try:
                                text_content = raw.decode("utf-8")
                            except UnicodeDecodeError:
                                text_content = base64.b64encode(raw).decode("ascii")
                            extracted_items.append({
                                "filename": member.name,
                                "content": text_content,
                                "file_size": member.size,
                            })
                return NodeResult(output_items=extracted_items)

            else:
                raise NodeExecutionError(
                    f"Unsupported compression operation '{params.operation}'.",
                    code="COMPRESSION_INVALID_OP",
                    node_id=ctx.node_id,
                    retryable=False,
                )

        except Exception as exc:
            if isinstance(exc, NodeExecutionError):
                raise
            raise NodeExecutionError(
                f"Compression operation '{params.operation}' failed: {exc}",
                code="COMPRESSION_ERROR",
                node_id=ctx.node_id,
                retryable=False,
            ) from exc
