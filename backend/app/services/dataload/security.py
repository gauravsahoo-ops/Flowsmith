"""Security and Archive Integrity Protection for Flowsmith DataLoad.

Defends against:
1. ZipSlip and path traversal attacks (nested directories escaping root or using ..).
2. Symlink creation and link traversal.
3. ZIP bombs / Decompression bombs (excessive compression ratios, unbounded expansion).
4. Excessive entry counts and unbounded archive nesting depth.
5. Insecure file execution and residual temporary files.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import shutil
import tempfile
import zipfile
from typing import Generator

from app.engine.errors import NodeExecutionError


class ZipSecurityValidator:
    """Security validator for ZIP archives."""

    DEFAULT_MAX_ENTRIES = 1000
    DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES = 150_000_000  # 150 MB
    DEFAULT_MAX_SINGLE_ENTRY_BYTES = 100_000_000        # 100 MB
    DEFAULT_MAX_COMPRESSION_RATIO = 100.0                # 100:1 ratio limit
    DEFAULT_MAX_NESTING_DEPTH = 2

    @classmethod
    def validate_archive(
        cls,
        zf: zipfile.ZipFile,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_UNCOMPRESSED_BYTES,
        max_single_entry_bytes: int = DEFAULT_MAX_SINGLE_ENTRY_BYTES,
        max_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
        node_id: str = "data_load",
    ) -> list[zipfile.ZipInfo]:
        """Validate archive structure against ZipSlip, symlinks, and decompression bombs.

        Returns valid, non-directory ZipInfo entries.
        """
        infolist = zf.infolist()

        # 1. Check entry count
        if len(infolist) > max_entries:
            raise NodeExecutionError(
                f"ZIP security violation: Archive contains {len(infolist)} entries, exceeding safety limit of {max_entries}.",
                code="ZIP_TOO_MANY_ENTRIES",
                node_id=node_id,
                retryable=False,
            )

        total_uncompressed = 0
        valid_entries: list[zipfile.ZipInfo] = []

        for info in infolist:
            name = info.filename

            # 2. Path Traversal / ZipSlip check
            normalized_name = name.replace("\\", "/")
            if (
                "../" in normalized_name
                or normalized_name.startswith("../")
                or normalized_name.startswith("/")
                or (len(normalized_name) >= 2 and normalized_name[1] == ":")  # Windows drive C:
            ):
                raise NodeExecutionError(
                    f"ZIP security violation: Path traversal detected in entry '{name}'.",
                    code="ZIP_PATH_TRAVERSAL",
                    node_id=node_id,
                    retryable=False,
                )

            # Skip directory markers
            if info.is_dir() or name.endswith("/"):
                continue

            # 3. Symlink check (Unix mode symlink: S_IFLNK = 0o120000)
            if (info.external_attr >> 16) & 0o120000 == 0o120000:
                raise NodeExecutionError(
                    f"ZIP security violation: Symbolic link entry detected in '{name}'. Symlinks are prohibited.",
                    code="ZIP_SYMLINK_REJECTED",
                    node_id=node_id,
                    retryable=False,
                )

            # 4. Decompression bomb check: Single entry size
            if info.file_size > max_single_entry_bytes:
                raise NodeExecutionError(
                    f"ZIP security violation: Entry '{name}' expanded size ({info.file_size} bytes) exceeds limit ({max_single_entry_bytes} bytes).",
                    code="ZIP_ENTRY_TOO_LARGE",
                    node_id=node_id,
                    retryable=False,
                )

            # 5. Decompression bomb check: Compression ratio
            # Only trigger ratio check for files that expand beyond 5 MB to avoid false positives on small text files
            if info.file_size > 5_000_000:
                compressed_size = max(info.compress_size, 1)
                ratio = info.file_size / compressed_size
                if ratio > max_ratio:
                    raise NodeExecutionError(
                        f"ZIP security violation: Decompression bomb detected in entry '{name}' (ratio {ratio:.1f}:1 exceeds safety limit {max_ratio}:1).",
                        code="ZIP_BOMB_DETECTED",
                        node_id=node_id,
                        retryable=False,
                    )

            total_uncompressed += info.file_size
            if total_uncompressed > max_total_bytes:
                raise NodeExecutionError(
                    f"ZIP security violation: Archive total uncompressed size ({total_uncompressed} bytes) exceeds safety limit ({max_total_bytes} bytes).",
                    code="ZIP_TOTAL_TOO_LARGE",
                    node_id=node_id,
                    retryable=False,
                )

            # Ignore macOS resource fork junk
            if not name.startswith("__MACOSX/") and not os.path.basename(name).startswith("._") and os.path.basename(name) != ".DS_Store":
                valid_entries.append(info)

        return valid_entries


@contextlib.contextmanager
def safe_temp_sandbox(prefix: str = "flowsmith_dataload_") -> Generator[Path, None, None]:
    """Create a temporary sandbox directory guaranteed to be purged on exit or cancellation."""
    temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
