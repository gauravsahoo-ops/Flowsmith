"""Extensible Format Registry and Handlers for Flowsmith DataLoad.

Defines a modular architecture that cleanly isolates format handling into pluggable components:
- Delimited text (CSV, TSV, custom delimiters)
- ZIP archives (single or multi-file combined, nested)
- GZIP compressed archives
- Extension points for future handlers (JSON/NDJSON, Excel, XML)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import csv
from dataclasses import dataclass, field
import gzip
import io
from typing import Any, Generator

from app.engine.errors import NodeExecutionError
from app.services.dataload.archive import ArchiveManager, ExtractedFileItem


@dataclass
class DataLoadOptions:
    delimiter: str | None = None
    encoding: str = "utf-8"
    has_header: bool = True
    quotechar: str = '"'
    escapechar: str | None = None
    batch_size: int = 1000
    skip_empty_lines: bool = True
    strip_whitespace: bool = True
    null_values: list[str] = field(default_factory=lambda: ["", "null", "NULL", "None", "NA", "N/A"])
    # Archive options
    archive_inner_file: str = ""
    archive_pattern: str = "*"
    archive_process_mode: str = "single"  # "single" | "combine"
    archive_header_mode: str = "union"    # "union" | "strict" | "first"
    max_nesting_depth: int = 2
    row_limit: int = 0                    # 0 for unlimited


class FormatHandler(ABC):
    """Abstract base class for all DataLoad format handlers."""

    @abstractmethod
    def can_handle(self, filename: str, header_bytes: bytes) -> bool:
        """Determine if this handler can process the given file."""
        pass

    @abstractmethod
    def parse_stream(
        self,
        raw_bytes: bytes,
        filename: str,
        options: DataLoadOptions,
        *,
        node_id: str = "data_load",
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Stream parsed records in bounded chunks."""
        pass


class DelimitedFormatHandler(FormatHandler):
    """Handler for CSV, TSV, and custom delimited text."""

    def can_handle(self, filename: str, header_bytes: bytes) -> bool:
        lower = filename.lower()
        if lower.endswith((".csv", ".tsv", ".tab", ".txt", ".dat")):
            return True
        # Try checking if content is plain ASCII/UTF-8 text
        try:
            sample = header_bytes[:512].decode("utf-8-sig")
            return any(d in sample for d in (",", "\t", ";", "|"))
        except Exception:
            return False

    def parse_stream(
        self,
        raw_bytes: bytes,
        filename: str,
        options: DataLoadOptions,
        *,
        node_id: str = "data_load",
    ) -> Generator[list[dict[str, Any]], None, None]:
        text = raw_bytes.decode("utf-8-sig", errors="replace")
        yield from self._stream_delimited_text(
            text=text,
            source_filename=filename,
            archive_path=filename,
            options=options,
            node_id=node_id,
        )

    @classmethod
    def _stream_delimited_text(
        cls,
        text: str,
        source_filename: str,
        archive_path: str,
        options: DataLoadOptions,
        *,
        node_id: str = "data_load",
        starting_row_number: int = 1,
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Stream parsed rows from a text string with dialect sniffing and metadata injection."""
        stream = io.StringIO(text)
        first_line = stream.readline()
        if not first_line:
            return

        # Delimiter detection
        delimiter = options.delimiter
        if delimiter in ("\\t", "tab", "\t"):
            delimiter = "\t"
        elif not delimiter:
            lower_name = source_filename.lower()
            if lower_name.endswith((".tsv", ".tab")):
                delimiter = "\t"
            else:
                tabs = first_line.count("\t")
                commas = first_line.count(",")
                semis = first_line.count(";")
                pipes = first_line.count("|")

                if tabs > commas and tabs > 0:
                    delimiter = "\t"
                elif semis > commas and semis > 0:
                    delimiter = ";"
                elif pipes > commas and pipes > 0:
                    delimiter = "|"
                else:
                    delimiter = ","

        full_content = first_line + stream.read()
        try:
            reader = csv.reader(
                io.StringIO(full_content),
                delimiter=delimiter,
                quotechar=options.quotechar or '"',
                escapechar=options.escapechar or None,
                skipinitialspace=options.strip_whitespace,
            )
        except Exception as exc:
            raise NodeExecutionError(
                f"Delimiter parsing failed on {source_filename}: {exc}",
                code="MALFORMED_DELIMITED_FILE",
                node_id=node_id,
                retryable=False,
            ) from exc

        headers: list[str] = []
        if options.has_header:
            try:
                raw_headers = next(reader)
                headers = [h.strip() if options.strip_whitespace else h for h in raw_headers]
            except StopIteration:
                return

        chunk: list[dict[str, Any]] = []
        row_num = starting_row_number
        null_set = set(options.null_values)
        total_emitted = 0

        for raw_row in reader:
            row_num += 1
            if options.skip_empty_lines and not any(f.strip() for f in raw_row):
                continue

            row_dict: dict[str, Any] = {}
            if options.has_header:
                for idx, h in enumerate(headers):
                    val = raw_row[idx] if idx < len(raw_row) else None
                    if val is not None and options.strip_whitespace and isinstance(val, str):
                        val = val.strip()
                    if val in null_set:
                        val = None
                    row_dict[h] = val
            else:
                for idx, val in enumerate(raw_row):
                    if val is not None and options.strip_whitespace and isinstance(val, str):
                        val = val.strip()
                    if val in null_set:
                        val = None
                    row_dict[f"column_{idx+1}"] = val

            # Inject source tracking metadata
            row_dict["_row_number"] = row_num
            row_dict["_source_file"] = source_filename
            row_dict["_archive_path"] = archive_path

            chunk.append(row_dict)
            total_emitted += 1

            if options.row_limit > 0 and total_emitted >= options.row_limit:
                yield chunk
                return

            if len(chunk) >= options.batch_size:
                yield chunk
                chunk = []

        if chunk:
            yield chunk


class ZipArchiveFormatHandler(FormatHandler):
    """Handler for ZIP archives containing single or multiple CSV/TSV files."""

    def can_handle(self, filename: str, header_bytes: bytes) -> bool:
        return (
            filename.lower().endswith(".zip")
            or header_bytes.startswith(b"PK\x03\x04")
            or header_bytes.startswith(b"PK\x05\x06")
        )

    def parse_stream(
        self,
        raw_bytes: bytes,
        filename: str,
        options: DataLoadOptions,
        *,
        node_id: str = "data_load",
    ) -> Generator[list[dict[str, Any]], None, None]:
        extracted_files, unsupported = ArchiveManager.extract_tabular_files(
            raw_bytes,
            target_entry=options.archive_inner_file,
            path_pattern=options.archive_pattern,
            process_mode=options.archive_process_mode,
            max_nesting_depth=options.max_nesting_depth,
            node_id=node_id,
        )

        if not extracted_files:
            raise NodeExecutionError(
                f"No matching tabular files found in archive '{filename}'. Unsupported entries: {unsupported}",
                code="NO_SUPPORTED_FILES",
                node_id=node_id,
                retryable=False,
            )

        # Process single or combine
        if options.archive_process_mode == "combine" and len(extracted_files) > 1:
            yield from self._stream_combined_files(extracted_files, options, node_id=node_id)
        else:
            # Single file mode (first extracted item)
            item = extracted_files[0]
            # Override delimiter if item format is TSV and none specified
            opts = options
            if item.format == "tsv" and not options.delimiter:
                opts = DataLoadOptions(**{**options.__dict__, "delimiter": "\t"})

            yield from DelimitedFormatHandler._stream_delimited_text(
                text=item.text,
                source_filename=item.filename,
                archive_path=item.archive_path,
                options=opts,
                node_id=node_id,
            )

    @classmethod
    def _stream_combined_files(
        cls,
        files: list[ExtractedFileItem],
        options: DataLoadOptions,
        *,
        node_id: str = "data_load",
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Combine multiple tabular files with header validation policies."""
        first_headers: list[str] | None = None
        global_row_offset = 0

        for idx, item in enumerate(files):
            # Parse header of current file to validate
            first_line = item.text.splitlines()[:1]
            if not first_line:
                continue

            delim = options.delimiter or (item.suggested_delimiter if item.format == "tsv" else ",")
            try:
                current_headers = [
                    h.strip() if options.strip_whitespace else h
                    for h in next(csv.reader([first_line[0]], delimiter=delim))
                ]
            except Exception:
                current_headers = []

            if first_headers is None:
                first_headers = current_headers
            else:
                # Validate according to archive_header_mode
                if options.archive_header_mode == "strict" and current_headers != first_headers:
                    raise NodeExecutionError(
                        f"Header mismatch in combined archive: '{item.archive_path}' headers {current_headers} do not match initial headers {first_headers}.",
                        code="ARCHIVE_HEADER_MISMATCH",
                        node_id=node_id,
                        retryable=False,
                    )

            opts = options
            if item.format == "tsv" and not options.delimiter:
                opts = DataLoadOptions(**{**options.__dict__, "delimiter": "\t"})

            for batch in DelimitedFormatHandler._stream_delimited_text(
                text=item.text,
                source_filename=item.filename,
                archive_path=item.archive_path,
                options=opts,
                node_id=node_id,
                starting_row_number=global_row_offset,
            ):
                yield batch
                global_row_offset += len(batch)


class GzipFormatHandler(FormatHandler):
    """Handler for GZIP compressed files (.gz)."""

    def can_handle(self, filename: str, header_bytes: bytes) -> bool:
        return filename.lower().endswith(".gz") or header_bytes.startswith(b"\x1f\x8b")

    def parse_stream(
        self,
        raw_bytes: bytes,
        filename: str,
        options: DataLoadOptions,
        *,
        node_id: str = "data_load",
    ) -> Generator[list[dict[str, Any]], None, None]:
        try:
            decompressed = gzip.decompress(raw_bytes)
            decompressed_name = filename[:-3] if filename.lower().endswith(".gz") else f"{filename}.decompressed"
            text = decompressed.decode("utf-8-sig", errors="replace")

            yield from DelimitedFormatHandler._stream_delimited_text(
                text=text,
                source_filename=decompressed_name,
                archive_path=filename,
                options=options,
                node_id=node_id,
            )
        except Exception as exc:
            raise NodeExecutionError(
                f"Corrupted or invalid GZIP file '{filename}': {exc}",
                code="CORRUPT_GZIP",
                node_id=node_id,
                retryable=False,
            ) from exc


class FormatRegistry:
    """Registry managing available file format handlers."""

    _handlers: list[FormatHandler] = [
        ZipArchiveFormatHandler(),
        GzipFormatHandler(),
        DelimitedFormatHandler(),
    ]

    SUPPORTED_FORMATS = [
        "csv",
        "tsv",
        "zip",
        "gzip",
    ]

    PLANNED_FORMATS = [
        "json",
        "jsonl",
        "ndjson",
        "xml",
        "xlsx",
    ]

    @classmethod
    def register_handler(cls, handler: FormatHandler, at_beginning: bool = True) -> None:
        """Register a custom format handler."""
        if at_beginning:
            cls._handlers.insert(0, handler)
        else:
            cls._handlers.append(handler)

    @classmethod
    def get_handler(cls, filename: str, header_bytes: bytes) -> FormatHandler:
        """Find the matching format handler."""
        for handler in cls._handlers:
            if handler.can_handle(filename, header_bytes):
                return handler
        raise NodeExecutionError(
            f"Unsupported file format for '{filename}'. Currently supported formats: {cls.SUPPORTED_FORMATS}",
            code="UNSUPPORTED_FORMAT",
            node_id="data_load",
            retryable=False,
        )
