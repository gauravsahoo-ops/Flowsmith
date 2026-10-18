"""Enterprise CSV Processing Service for Flowsmith.

Handles:
1. Streaming / chunked CSV parsing with BOM handling, dialect sniffing, and row-level numbering.
2. Field mapping & validation (Salesforce Contact schema bounds & custom schemas).
3. Configurable deduplication (source-file, database, salesforce rejections).
4. Bounded batch database persistence via SQLAlchemy with transaction rollbacks.
5. Result reconciliation between original CSV rows, database state, and Salesforce ingest responses.
"""

from __future__ import annotations

import base64
import csv
import gzip
import io
import os
from pathlib import Path
import re
import tarfile
import urllib.parse
import uuid
import time
import zipfile
from typing import Any, Generator
from dataclasses import dataclass, field

import httpx
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.objectstore.factory import get_object_store
from app.models.staged_record import StagedContactRecord


@dataclass
class ExtractedSourceMeta:
    text: str
    detected_format: str = "csv"  # "csv", "tsv", "zip", "gzip", "tar", "text"
    inner_filename: str | None = None
    archive_files: list[str] = field(default_factory=list)
    suggested_delimiter: str | None = None
    source_type: str = "raw"  # "url", "file_path", "file_id", "upload_data_url", "inline", "raw"



@dataclass
class CsvParseOptions:
    delimiter: str | None = None
    quotechar: str = '"'
    escapechar: str | None = None
    encoding: str = "utf-8"
    has_header: bool = True
    batch_size: int = 1000
    skip_empty_lines: bool = True
    strip_whitespace: bool = True


@dataclass
class ValidationResult:
    valid_records: list[dict[str, Any]] = field(default_factory=list)
    invalid_records: list[dict[str, Any]] = field(default_factory=list)
    duplicate_records: list[dict[str, Any]] = field(default_factory=list)
    total_parsed: int = 0
    unique_count: int = 0
    duplicate_count: int = 0
    invalid_count: int = 0


@dataclass
class PersistenceResult:
    execution_id: str
    total_processed: int = 0
    inserted_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    invalid_count: int = 0
    failed_count: int = 0
    duration_ms: float = 0.0


# Standard Salesforce Contact constraints
SF_CONTACT_CONSTRAINTS = {
    "LastName": {"required": True, "max_length": 80},
    "FirstName": {"required": False, "max_length": 40},
    "Email": {"required": False, "max_length": 80, "type": "email"},
    "Phone": {"required": False, "max_length": 40},
    "Department": {"required": False, "max_length": 80},
    "Title": {"required": False, "max_length": 128},
    "MailingStreet": {"required": False, "max_length": 255},
    "MailingCity": {"required": False, "max_length": 40},
    "MailingState": {"required": False, "max_length": 80},
    "MailingPostalCode": {"required": False, "max_length": 20},
    "MailingCountry": {"required": False, "max_length": 80},
    "Description": {"required": False, "max_length": 32000},
}

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CsvService:
    """Production CSV, TSV, and Archive ingestion, validation, deduplication, and persistence engine."""

    @staticmethod
    def fetch_url_content(url: str, timeout: float = 60.0) -> tuple[bytes, str]:
        """Fetch remote file content from an HTTP or HTTPS link with timeout and redirect handling.

        Returns a tuple of (content_bytes, filename_hint).
        """
        clean_url = url.strip()
        filename_hint = ""
        parsed_url = urllib.parse.urlparse(clean_url)
        path_name = os.path.basename(parsed_url.path)
        if path_name:
            filename_hint = path_name

        headers = {
            "User-Agent": "Flowsmith-Ingest-Engine/1.0 (Enterprise CSV/TSV/Archive Parser)"
        }
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(clean_url, headers=headers)
            resp.raise_for_status()

            cd = resp.headers.get("content-disposition", "")
            if "filename=" in cd:
                match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd, re.IGNORECASE)
                if match:
                    filename_hint = match.group(1).strip()

            return resp.content, filename_hint

    @classmethod
    def extract_from_archive_bytes(
        cls,
        raw_bytes: bytes,
        filename_hint: str = "",
        archive_inner_file: str | None = None,
    ) -> ExtractedSourceMeta:
        """Extract tabular text (CSV, TSV) from raw bytes, ZIP archives, GZIP files, or TAR bundles."""
        lowered_name = filename_hint.lower()

        # 1. Check for ZIP archive (Magic bytes: PK\x03\x04, PK\x05\x06, PK\x07\x08, or .zip extension)
        is_zip = (
            raw_bytes.startswith(b"PK\x03\x04")
            or raw_bytes.startswith(b"PK\x05\x06")
            or raw_bytes.startswith(b"PK\x07\x08")
            or lowered_name.endswith(".zip")
        )
        if is_zip:
            try:
                with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                    all_entries = zf.namelist()
                    valid_files = [
                        name for name in all_entries
                        if not name.endswith("/")
                        and not name.startswith("__MACOSX/")
                        and not os.path.basename(name).startswith("._")
                        and os.path.basename(name) != ".DS_Store"
                    ]
                    if not valid_files:
                        raise ValueError(f"ZIP archive contains no usable files. Entries: {all_entries}")

                    chosen_entry = None
                    if archive_inner_file and archive_inner_file.strip():
                        target = archive_inner_file.strip()
                        if target in valid_files:
                            chosen_entry = target
                        else:
                            for v in valid_files:
                                if os.path.basename(v).lower() == target.lower() or v.lower() == target.lower():
                                    chosen_entry = v
                                    break
                        if not chosen_entry:
                            raise ValueError(
                                f"Requested inner file '{target}' not found in ZIP. Available files: {valid_files}"
                            )
                    else:
                        candidates = [v for v in valid_files if v.lower().endswith((".csv", ".tsv", ".tab", ".txt", ".dat"))]
                        chosen_entry = candidates[0] if candidates else valid_files[0]

                    inner_data = zf.read(chosen_entry)
                    decoded_text = inner_data.decode("utf-8-sig", errors="replace")
                    is_tsv = chosen_entry.lower().endswith((".tsv", ".tab"))
                    return ExtractedSourceMeta(
                        text=decoded_text,
                        detected_format="zip",
                        inner_filename=chosen_entry,
                        archive_files=valid_files,
                        suggested_delimiter="\t" if is_tsv else None,
                        source_type="archive_zip",
                    )
            except zipfile.BadZipFile as exc:
                raise ValueError(f"Corrupted or invalid ZIP archive: {exc}") from exc

        # 2. Check for GZIP compression (Magic bytes: \x1f\x8b or .gz extension)
        is_gzip = raw_bytes.startswith(b"\x1f\x8b") or lowered_name.endswith((".gz", ".gzip", ".tgz"))
        if is_gzip:
            try:
                decompressed = gzip.decompress(raw_bytes)
                if lowered_name.endswith((".tar.gz", ".tgz")) or decompressed.startswith(b"ustar"):
                    return cls._extract_from_tar(decompressed, filename_hint, archive_inner_file)

                inner_name = filename_hint[:-3] if lowered_name.endswith(".gz") else "decompressed.csv"
                is_tsv = inner_name.lower().endswith((".tsv", ".tab"))
                decoded_text = decompressed.decode("utf-8-sig", errors="replace")
                return ExtractedSourceMeta(
                    text=decoded_text,
                    detected_format="gzip",
                    inner_filename=inner_name,
                    archive_files=[inner_name],
                    suggested_delimiter="\t" if is_tsv else None,
                    source_type="archive_gzip",
                )
            except Exception as exc:
                raise ValueError(f"Corrupted or invalid GZIP file: {exc}") from exc

        # 3. Check for TAR archive
        if lowered_name.endswith(".tar"):
            return cls._extract_from_tar(raw_bytes, filename_hint, archive_inner_file)

        # 4. Standard uncompressed bytes (CSV, TSV, text)
        decoded_text = raw_bytes.decode("utf-8-sig", errors="replace")
        is_tsv = lowered_name.endswith((".tsv", ".tab")) or (
            "\t" in decoded_text and decoded_text.count("\t") > decoded_text.count(",")
        )
        return ExtractedSourceMeta(
            text=decoded_text,
            detected_format="tsv" if is_tsv else "csv",
            inner_filename=filename_hint or None,
            archive_files=[filename_hint] if filename_hint else [],
            suggested_delimiter="\t" if is_tsv else None,
            source_type="raw_bytes",
        )

    @classmethod
    def _extract_from_tar(
        cls,
        raw_bytes: bytes,
        filename_hint: str = "",
        archive_inner_file: str | None = None,
    ) -> ExtractedSourceMeta:
        """Extract tabular content from a TAR archive."""
        try:
            with tarfile.open(fileobj=io.BytesIO(raw_bytes)) as tf:
                members = [m for m in tf.getmembers() if m.isfile() and not m.name.startswith("__MACOSX")]
                member_names = [m.name for m in members]
                if not members:
                    raise ValueError(f"TAR archive contains no regular files. Available: {member_names}")

                chosen_member = None
                if archive_inner_file and archive_inner_file.strip():
                    target = archive_inner_file.strip()
                    for m in members:
                        if m.name == target or os.path.basename(m.name).lower() == target.lower():
                            chosen_member = m
                            break
                    if not chosen_member:
                        raise ValueError(f"Requested inner file '{target}' not found in TAR. Available: {member_names}")
                else:
                    candidates = [m for m in members if m.name.lower().endswith((".csv", ".tsv", ".tab", ".txt", ".dat"))]
                    chosen_member = candidates[0] if candidates else members[0]

                extracted_f = tf.extractfile(chosen_member)
                if not extracted_f:
                    raise ValueError(f"Could not read TAR member '{chosen_member.name}'")
                content = extracted_f.read().decode("utf-8-sig", errors="replace")
                is_tsv = chosen_member.name.lower().endswith((".tsv", ".tab"))
                return ExtractedSourceMeta(
                    text=content,
                    detected_format="tar",
                    inner_filename=chosen_member.name,
                    archive_files=member_names,
                    suggested_delimiter="\t" if is_tsv else None,
                    source_type="archive_tar",
                )
        except Exception as exc:
            raise ValueError(f"Corrupted or invalid TAR archive: {exc}") from exc

    @classmethod
    def get_tabular_stream_and_meta(
        cls,
        source: str | bytes | io.TextIOBase,
        *,
        file_id: str | None = None,
        download_url: str | None = None,
        archive_inner_file: str | None = None,
    ) -> tuple[io.StringIO, ExtractedSourceMeta]:
        """Resolve tabular text stream and metadata from URL, base64 data URL, archive, file path, or string."""
        # 1. Download link / URL
        if download_url and download_url.strip():
            raw_bytes, hint = cls.fetch_url_content(download_url)
            meta = cls.extract_from_archive_bytes(raw_bytes, filename_hint=hint, archive_inner_file=archive_inner_file)
            meta.source_type = "url"
            return io.StringIO(meta.text), meta

        # 2. Flowsmith ObjectStore file_id
        if file_id and file_id.strip():
            store = get_object_store()
            raw_bytes = store.get(file_id.strip())
            meta = cls.extract_from_archive_bytes(raw_bytes, filename_hint=file_id, archive_inner_file=archive_inner_file)
            meta.source_type = "file_id"
            return io.StringIO(meta.text), meta

        # 3. Direct bytes input
        if isinstance(source, bytes):
            meta = cls.extract_from_archive_bytes(source, archive_inner_file=archive_inner_file)
            return io.StringIO(meta.text), meta

        # 4. TextIOBase stream
        if isinstance(source, io.TextIOBase):
            content = source.read()
            is_tsv = "\t" in content and content.count("\t") > content.count(",")
            meta = ExtractedSourceMeta(
                text=content,
                detected_format="tsv" if is_tsv else "csv",
                suggested_delimiter="\t" if is_tsv else None,
                source_type="stream",
            )
            return io.StringIO(content), meta

        # 5. String input (URL, base64 data URL, file path, or inline text)
        if isinstance(source, str):
            clean_source = source.strip()

            # 5a. Remote URL passed as source string
            if clean_source.startswith(("http://", "https://")):
                raw_bytes, hint = cls.fetch_url_content(clean_source)
                meta = cls.extract_from_archive_bytes(raw_bytes, filename_hint=hint, archive_inner_file=archive_inner_file)
                meta.source_type = "url"
                return io.StringIO(meta.text), meta

            # 5b. Base64 Data URL (e.g. data:application/zip;base64,... or data:text/csv;base64,...)
            if clean_source.startswith("data:") and ";base64," in clean_source:
                header, b64_data = clean_source.split(";base64,", 1)
                raw_bytes = base64.b64decode(b64_data)
                hint = "archive.zip" if "zip" in header.lower() else ("data.gz" if "gzip" in header.lower() else "data.csv")
                meta = cls.extract_from_archive_bytes(raw_bytes, filename_hint=hint, archive_inner_file=archive_inner_file)
                meta.source_type = "upload_data_url"
                return io.StringIO(meta.text), meta

            # 5c. Check candidate paths on disk
            tabular_exts = (".csv", ".tsv", ".tab", ".zip", ".gz", ".tgz", ".tar", ".txt", ".dat")
            is_potential_path = (
                "\n" not in clean_source
                and (clean_source.lower().endswith(tabular_exts) or "/" in clean_source or "\\" in clean_source or os.path.isfile(clean_source))
            )
            if is_potential_path:
                candidates = [
                    Path(clean_source),
                    Path.cwd() / clean_source,
                    Path.cwd().parent / clean_source,
                    Path(__file__).resolve().parents[2] / clean_source,
                    Path(__file__).resolve().parents[3] / clean_source,
                    Path(r"c:\Flowsmith") / clean_source,
                    Path("/app") / clean_source,
                    Path("/app/backend") / clean_source,
                ]
                for cand in candidates:
                    try:
                        if cand.is_file():
                            raw_bytes = cand.read_bytes()
                            meta = cls.extract_from_archive_bytes(
                                raw_bytes,
                                filename_hint=cand.name,
                                archive_inner_file=archive_inner_file,
                            )
                            meta.source_type = "file_path"
                            return io.StringIO(meta.text), meta
                    except Exception:
                        continue

            # 5d. Inline CSV/TSV raw text string
            is_tsv = "\t" in source and source.count("\t") > source.count(",")
            meta = ExtractedSourceMeta(
                text=source,
                detected_format="tsv" if is_tsv else "csv",
                suggested_delimiter="\t" if is_tsv else None,
                source_type="inline",
            )
            return io.StringIO(source), meta

        raise ValueError("Invalid tabular data source provided: must be URL, file path, base64 data URL, string, or bytes.")

    @classmethod
    def get_csv_text_from_source(
        cls,
        source: str | bytes,
        file_id: str | None = None,
        *,
        download_url: str | None = None,
        archive_inner_file: str | None = None,
    ) -> io.StringIO:
        """Resolve CSV/TSV content from raw string, raw bytes, URL, or Flowsmith object store file_id."""
        stream, _ = cls.get_tabular_stream_and_meta(
            source,
            file_id=file_id,
            download_url=download_url,
            archive_inner_file=archive_inner_file,
        )
        return stream

    @classmethod
    def stream_parsed_rows(
        cls,
        csv_source: str | bytes | io.TextIOBase,
        options: CsvParseOptions | None = None,
        *,
        file_id: str | None = None,
        download_url: str | None = None,
        archive_inner_file: str | None = None,
        source_meta_out: dict[str, Any] | None = None,
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Stream parsed CSV, TSV, or Archive rows in bounded chunks, preserving 1-indexed source row numbers."""
        opts = options or CsvParseOptions()

        text_stream, meta = cls.get_tabular_stream_and_meta(
            csv_source,
            file_id=file_id,
            download_url=download_url,
            archive_inner_file=archive_inner_file,
        )

        first_line = text_stream.readline()
        if not first_line:
            if source_meta_out is not None:
                source_meta_out.update({
                    "detected_format": meta.detected_format,
                    "inner_filename": meta.inner_filename,
                    "archive_files": meta.archive_files,
                    "detected_delimiter": opts.delimiter or ",",
                    "source_type": meta.source_type,
                })
            return

        # Delimiter resolution: explicit -> meta suggestion -> heuristic sniff
        delimiter = opts.delimiter
        if delimiter in ("\\t", "tab", "\t"):
            delimiter = "\t"
        elif not delimiter:
            if meta.suggested_delimiter:
                delimiter = meta.suggested_delimiter
            else:
                tab_cnt = first_line.count("\t")
                comma_cnt = first_line.count(",")
                semi_cnt = first_line.count(";")
                pipe_cnt = first_line.count("|")

                if tab_cnt > comma_cnt and tab_cnt > 0:
                    delimiter = "\t"
                elif semi_cnt > comma_cnt and semi_cnt > 0:
                    delimiter = ";"
                elif pipe_cnt > comma_cnt and pipe_cnt > 0:
                    delimiter = "|"
                else:
                    delimiter = ","

        if source_meta_out is not None:
            source_meta_out.update({
                "detected_format": "tsv" if delimiter == "\t" and meta.detected_format == "csv" else meta.detected_format,
                "inner_filename": meta.inner_filename,
                "archive_files": meta.archive_files,
                "detected_delimiter": delimiter,
                "source_type": meta.source_type,
            })

        # Re-seek or reconstruct stream
        full_content = first_line + text_stream.read()
        reader = csv.reader(
            io.StringIO(full_content),
            delimiter=delimiter,
            quotechar=opts.quotechar,
            escapechar=opts.escapechar,
            skipinitialspace=opts.strip_whitespace,
        )

        headers: list[str] = []
        if opts.has_header:
            try:
                raw_headers = next(reader)
                headers = [h.strip() for h in raw_headers]
            except StopIteration:
                return

        chunk: list[dict[str, Any]] = []
        row_num = 1 if opts.has_header else 0

        for raw_row in reader:
            row_num += 1
            if opts.skip_empty_lines and not any(f.strip() for f in raw_row):
                continue

            if opts.has_header:
                row_dict = {}
                for idx, h in enumerate(headers):
                    val = raw_row[idx] if idx < len(raw_row) else None
                    if val is not None and opts.strip_whitespace and isinstance(val, str):
                        val = val.strip()
                    row_dict[h] = val if val != "" else None
                row_dict["_row_number"] = row_num
                chunk.append(row_dict)
            else:
                row_dict: dict[str, Any] = {f"column_{i+1}": (v.strip() if opts.strip_whitespace else v) for i, v in enumerate(raw_row)}
                row_dict["_row_number"] = row_num
                chunk.append(row_dict)

            if len(chunk) >= opts.batch_size:
                yield chunk
                chunk = []

        if chunk:
            yield chunk

    @classmethod
    def map_and_validate(
        cls,
        rows: list[dict[str, Any]],
        field_mapping: dict[str, str],
        target_object: str = "Contact",
        duplicate_policy: str = "skip",  # 'skip' | 'update' | 'error'
        dedup_key: str = "Email",
        seen_keys: set[str] | None = None,
    ) -> ValidationResult:
        """Map CSV source columns to Salesforce target fields, perform schema validation, and detect duplicates."""
        result = ValidationResult()
        seen = seen_keys if seen_keys is not None else set()
        constraints = SF_CONTACT_CONSTRAINTS if target_object == "Contact" else {}

        # If no field_mapping provided, default to identity mapping for all non-internal columns
        effective_mapping = dict(field_mapping) if field_mapping else {}
        if not effective_mapping and rows:
            effective_mapping = {k: k for k in rows[0].keys() if not k.startswith("_")}

        for row in rows:
            result.total_parsed += 1
            row_num = row.get("_row_number", result.total_parsed + 1)
            mapped_record: dict[str, Any] = {}
            validation_errors: list[str] = []

            # 1. Apply field mapping
            for source_col, target_field in effective_mapping.items():
                val = row.get(source_col)
                mapped_record[target_field] = val

            # Preserve source metadata fields
            for meta_key in ("_source_file", "_archive_path"):
                if meta_key in row:
                    mapped_record[meta_key] = row[meta_key]

            # 2. Schema Validation
            for field_name, rule in constraints.items():
                val = mapped_record.get(field_name)
                # Check required
                if rule.get("required") and (val is None or str(val).strip() == ""):
                    validation_errors.append(f"Required field '{field_name}' is missing or empty.")
                    continue

                if val is not None:
                    str_val = str(val).strip()
                    # Check max length
                    max_len = rule.get("max_length")
                    if isinstance(max_len, int) and len(str_val) > max_len:
                        validation_errors.append(
                            f"Field '{field_name}' exceeds maximum length of {max_len} (got {len(str_val)})."
                        )
                    # Check email format
                    if rule.get("type") == "email" and str_val:
                        if not EMAIL_REGEX.match(str_val):
                            validation_errors.append(f"Field '{field_name}' has invalid email format: '{str_val}'.")

            mapped_record["_row_number"] = row_num

            # If validation failed, route to invalid_records
            if validation_errors:
                result.invalid_records.append({
                    "row_number": row_num,
                    "record": mapped_record,
                    "errors": validation_errors,
                })
                result.invalid_count += 1
                continue

            # 3. Duplicate Detection
            key_val = mapped_record.get(dedup_key)
            if key_val:
                key_norm = str(key_val).lower().strip()
                if key_norm in seen:
                    result.duplicate_count += 1
                    result.duplicate_records.append({
                        "row_number": row_num,
                        "record": mapped_record,
                        "duplicate_key": dedup_key,
                        "duplicate_value": key_val,
                    })
                    if duplicate_policy == "skip":
                        continue
                    elif duplicate_policy == "error":
                        result.invalid_records.append({
                            "row_number": row_num,
                            "record": mapped_record,
                            "errors": [f"Duplicate {dedup_key} '{key_val}' rejected by duplicate policy."],
                        })
                        result.invalid_count += 1
                        continue
                else:
                    seen.add(key_norm)

            result.valid_records.append(mapped_record)
            result.unique_count += 1

        return result

    @classmethod
    def persist_staged_records(
        cls,
        db: Session,
        execution_id: str,
        valid_records: list[dict[str, Any]],
        duplicate_records: list[dict[str, Any]] | None = None,
        invalid_records: list[dict[str, Any]] | None = None,
        batch_size: int = 1000,
    ) -> PersistenceResult:
        """Persist records in bounded batches using parameterized database transactions."""
        start_time = time.monotonic()
        res = PersistenceResult(execution_id=execution_id)

        dup_rows = duplicate_records or []
        inv_rows = invalid_records or []

        # 1. Insert Valid Records in Bounded Batches (High-Performance Bulk Insert)
        valid_dicts: list[dict[str, Any]] = []
        for rec in valid_records:
            valid_dicts.append({
                "id": f"stg_{uuid.uuid4().hex[:16]}",
                "execution_id": execution_id,
                "row_number": rec.get("_row_number", 0),
                "first_name": rec.get("FirstName"),
                "last_name": rec.get("LastName") or "Unknown",
                "email": rec.get("Email"),
                "phone": rec.get("Phone"),
                "department": rec.get("Department"),
                "title": rec.get("Title"),
                "mailing_street": rec.get("MailingStreet"),
                "mailing_city": rec.get("MailingCity"),
                "mailing_state": rec.get("MailingState"),
                "mailing_postal_code": rec.get("MailingPostalCode"),
                "mailing_country": rec.get("MailingCountry"),
                "description": rec.get("Description"),
                "raw_data": rec,
                "status": "staged",
                "error_message": None,
            })
            if len(valid_dicts) >= batch_size:
                db.execute(insert(StagedContactRecord), valid_dicts)
                db.commit()
                res.inserted_count += len(valid_dicts)
                valid_dicts = []

        if valid_dicts:
            db.execute(insert(StagedContactRecord), valid_dicts)
            db.commit()
            res.inserted_count += len(valid_dicts)

        # 2. Record Duplicates (Status: duplicate, skipped)
        dup_dicts: list[dict[str, Any]] = []
        for d in dup_rows:
            rec = d.get("record", {})
            dup_dicts.append({
                "id": f"stg_{uuid.uuid4().hex[:16]}",
                "execution_id": execution_id,
                "row_number": d.get("row_number", 0),
                "first_name": rec.get("FirstName"),
                "last_name": rec.get("LastName") or "Unknown",
                "email": rec.get("Email"),
                "phone": rec.get("Phone"),
                "department": rec.get("Department"),
                "title": rec.get("Title"),
                "mailing_street": rec.get("MailingStreet"),
                "mailing_city": rec.get("MailingCity"),
                "mailing_state": rec.get("MailingState"),
                "mailing_postal_code": rec.get("MailingPostalCode"),
                "mailing_country": rec.get("MailingCountry"),
                "description": rec.get("Description"),
                "raw_data": rec,
                "status": "duplicate",
                "error_message": f"Duplicate {d.get('duplicate_key')} ({d.get('duplicate_value')})",
            })
            if len(dup_dicts) >= batch_size:
                db.execute(insert(StagedContactRecord), dup_dicts)
                db.commit()
                res.duplicate_count += len(dup_dicts)
                res.skipped_count += len(dup_dicts)
                dup_dicts = []

        if dup_dicts:
            db.execute(insert(StagedContactRecord), dup_dicts)
            db.commit()
            res.duplicate_count += len(dup_dicts)
            res.skipped_count += len(dup_dicts)

        # 3. Record Invalid Rows (Status: invalid, skipped)
        inv_dicts: list[dict[str, Any]] = []
        for inv in inv_rows:
            rec = inv.get("record", {})
            inv_dicts.append({
                "id": f"stg_{uuid.uuid4().hex[:16]}",
                "execution_id": execution_id,
                "row_number": inv.get("row_number", 0),
                "first_name": rec.get("FirstName"),
                "last_name": rec.get("LastName") or "Unknown",
                "email": rec.get("Email"),
                "phone": rec.get("Phone"),
                "department": rec.get("Department"),
                "title": rec.get("Title"),
                "mailing_street": rec.get("MailingStreet"),
                "mailing_city": rec.get("MailingCity"),
                "mailing_state": rec.get("MailingState"),
                "mailing_postal_code": rec.get("MailingPostalCode"),
                "mailing_country": rec.get("MailingCountry"),
                "description": rec.get("Description"),
                "raw_data": rec,
                "status": "invalid",
                "error_message": "; ".join(inv.get("errors", [])),
            })
            if len(inv_dicts) >= batch_size:
                db.execute(insert(StagedContactRecord), inv_dicts)
                db.commit()
                res.invalid_count += len(inv_dicts)
                inv_dicts = []

        if inv_dicts:
            db.execute(insert(StagedContactRecord), inv_dicts)
            db.commit()
            res.invalid_count += len(inv_dicts)

        res.total_processed = res.inserted_count + res.duplicate_count + res.invalid_count
        res.duration_ms = (time.monotonic() - start_time) * 1000
        return res

    @classmethod
    def reconcile_salesforce_results(
        cls,
        db: Session,
        execution_id: str,
        successful_records: list[dict[str, Any]],
        failed_records: list[dict[str, Any]] | None = None,
    ) -> dict[str, int]:
        """Reconcile Salesforce Ingestion results back to staged_contacts database rows."""
        counts = {"reconciled_success": 0, "reconciled_failed": 0}

        # Query all staged records for this execution ordered by row_number
        staged = db.scalars(
            select(StagedContactRecord)
            .where(StagedContactRecord.execution_id == execution_id)
            .where(StagedContactRecord.status == "staged")
            .order_by(StagedContactRecord.row_number)
        ).all()

        staged_by_email = {s.email.lower(): s for s in staged if s.email}

        # Reconcile successes
        for succ in successful_records:
            sf_id = succ.get("sf__Id") or succ.get("Id") or succ.get("id")
            email = (succ.get("Email") or succ.get("email") or "").lower()
            record = staged_by_email.get(email)
            if record:
                record.status = "uploaded"
                record.salesforce_id = sf_id
                counts["reconciled_success"] += 1

        # Reconcile failures
        if failed_records:
            for fail in failed_records:
                email = (fail.get("Email") or fail.get("email") or "").lower()
                err = fail.get("sf__Error") or fail.get("Error") or fail.get("error") or "Unknown upload failure"
                record = staged_by_email.get(email)
                if record:
                    record.status = "failed"
                    record.error_message = str(err)
                    counts["reconciled_failed"] += 1

        db.commit()
        return counts
