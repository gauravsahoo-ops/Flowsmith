"""Archive Inspection, Filtering, and Extraction Engine for Flowsmith DataLoad.

Supports:
1. Entry inspection before extraction with detection of candidate tabular files and unsupported files.
2. Single-entry selection vs Combine-all-matching mode.
3. Glob / path-pattern filtering (e.g. *.csv, data/**/*.tsv).
4. Nested ZIP archives within configurable safety limits (max_nesting_depth).
5. Source metadata preservation (_source_file, _archive_path, _row_number).
6. Safe extraction protected by ZipSecurityValidator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import io
import os
import zipfile

from app.engine.errors import NodeExecutionError
from app.services.dataload.security import ZipSecurityValidator


SUPPORTED_TABULAR_EXTENSIONS = (".csv", ".tsv", ".tab", ".txt", ".dat")


@dataclass
class ExtractedFileItem:
    filename: str
    archive_path: str
    text: str
    format: str  # "csv" | "tsv"
    suggested_delimiter: str  # "," or "\t"
    nested_depth: int = 0
    size_bytes: int = 0


@dataclass
class ArchiveInspectionResult:
    total_entries: int = 0
    supported_files: list[str] = field(default_factory=list)
    unsupported_files: list[str] = field(default_factory=list)
    nested_archives: list[str] = field(default_factory=list)
    total_uncompressed_bytes: int = 0


class ArchiveManager:
    """Enterprise archive inspector and extractor."""

    @classmethod
    def inspect_archive(
        cls,
        raw_bytes: bytes,
        *,
        node_id: str = "data_load",
    ) -> ArchiveInspectionResult:
        """Inspect archive entries without extracting payload data."""
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                valid_infos = ZipSecurityValidator.validate_archive(zf, node_id=node_id)
                res = ArchiveInspectionResult(total_entries=len(valid_infos))

                for info in valid_infos:
                    name = info.filename
                    res.total_uncompressed_bytes += info.file_size
                    lower = name.lower()
                    if lower.endswith(".zip"):
                        res.nested_archives.append(name)
                    elif lower.endswith(SUPPORTED_TABULAR_EXTENSIONS):
                        res.supported_files.append(name)
                    else:
                        res.unsupported_files.append(name)

                return res
        except zipfile.BadZipFile as exc:
            raise NodeExecutionError(
                f"Corrupted or invalid ZIP archive: {exc}",
                code="CORRUPT_ZIP",
                node_id=node_id,
                retryable=False,
            ) from exc

    @classmethod
    def extract_tabular_files(
        cls,
        raw_bytes: bytes,
        *,
        target_entry: str = "",
        path_pattern: str = "*",
        process_mode: str = "single",  # "single" | "combine"
        max_nesting_depth: int = 2,
        current_depth: int = 0,
        parent_archive_path: str = "",
        node_id: str = "data_load",
    ) -> tuple[list[ExtractedFileItem], list[str]]:
        """Safely extract tabular files from ZIP archive.

        Returns:
            (extracted_items, unsupported_entries_list)
        """
        extracted_items: list[ExtractedFileItem] = []
        unsupported_entries: list[str] = []

        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                valid_infos = ZipSecurityValidator.validate_archive(zf, node_id=node_id)

                # Process nested archives first if within depth limit
                nested_infos = [info for info in valid_infos if info.filename.lower().endswith(".zip")]
                for nested_info in nested_infos:
                    if current_depth + 1 > max_nesting_depth:
                        raise NodeExecutionError(
                            f"Archive security violation: Nested archive '{nested_info.filename}' exceeds maximum nesting depth ({max_nesting_depth}).",
                            code="ZIP_NESTING_DEPTH_EXCEEDED",
                            node_id=node_id,
                            retryable=False,
                        )
                    nested_bytes = zf.read(nested_info)
                    sub_parent = (
                        f"{parent_archive_path}/{nested_info.filename}"
                        if parent_archive_path
                        else nested_info.filename
                    )
                    sub_items, sub_unsupported = cls.extract_tabular_files(
                        nested_bytes,
                        target_entry=target_entry,
                        path_pattern=path_pattern,
                        process_mode=process_mode,
                        max_nesting_depth=max_nesting_depth,
                        current_depth=current_depth + 1,
                        parent_archive_path=sub_parent,
                        node_id=node_id,
                    )
                    extracted_items.extend(sub_items)
                    unsupported_entries.extend(sub_unsupported)

                # Collect direct files in this archive
                direct_infos = [info for info in valid_infos if not info.filename.lower().endswith(".zip")]
                for info in direct_infos:
                    name = info.filename
                    lower = name.lower()
                    if not lower.endswith(SUPPORTED_TABULAR_EXTENSIONS):
                        unsupported_entries.append(name)
                        continue

                    # Filter by target_entry or path_pattern
                    matches_target = False
                    if target_entry and target_entry.strip():
                        target = target_entry.strip().lower()
                        if lower == target or os.path.basename(lower) == target or lower.endswith("/" + target):
                            matches_target = True
                    else:
                        matches_target = True

                    matches_pattern = True
                    if path_pattern and path_pattern.strip() and path_pattern.strip() != "*":
                        pat = path_pattern.strip().lower()
                        matches_pattern = (
                            fnmatch.fnmatch(lower, pat)
                            or fnmatch.fnmatch(os.path.basename(lower), pat)
                        )

                    if matches_target and matches_pattern:
                        data_bytes = zf.read(info)
                        text = data_bytes.decode("utf-8-sig", errors="replace")
                        is_tsv = lower.endswith((".tsv", ".tab")) or (
                            "\t" in text and text.count("\t") > text.count(",")
                        )
                        full_path = (
                            f"{parent_archive_path}/{name}" if parent_archive_path else name
                        )
                        extracted_items.append(
                            ExtractedFileItem(
                                filename=os.path.basename(name),
                                archive_path=full_path,
                                text=text,
                                format="tsv" if is_tsv else "csv",
                                suggested_delimiter="\t" if is_tsv else ",",
                                nested_depth=current_depth,
                                size_bytes=len(data_bytes),
                            )
                        )

            # Apply process_mode
            if process_mode == "single" and len(extracted_items) > 1:
                # If target_entry was specified, prioritize exact match, otherwise first item
                if target_entry:
                    exact = [item for item in extracted_items if item.filename.lower() == target_entry.lower()]
                    extracted_items = [exact[0]] if exact else [extracted_items[0]]
                else:
                    extracted_items = [extracted_items[0]]

            if not extracted_items and not nested_infos:
                if target_entry:
                    raise NodeExecutionError(
                        f"Target entry '{target_entry}' was not found in archive.",
                        code="ENTRY_NOT_FOUND",
                        node_id=node_id,
                        retryable=False,
                    )
                elif direct_infos and not any(info.filename.lower().endswith(SUPPORTED_TABULAR_EXTENSIONS) for info in direct_infos):
                    raise NodeExecutionError(
                        f"Archive contains no supported tabular files (.csv, .tsv). Found: {[i.filename for i in direct_infos]}",
                        code="NO_SUPPORTED_FILES",
                        node_id=node_id,
                        retryable=False,
                    )

            return extracted_items, unsupported_entries
        except NodeExecutionError:
            raise
        except zipfile.BadZipFile as exc:
            raise NodeExecutionError(
                f"Corrupted or invalid ZIP archive: {exc}",
                code="CORRUPT_ZIP",
                node_id=node_id,
                retryable=False,
            ) from exc
        except Exception as exc:
            raise NodeExecutionError(
                f"Archive extraction failed: {exc}",
                code="ARCHIVE_EXTRACTION_ERROR",
                node_id=node_id,
                retryable=False,
            ) from exc
