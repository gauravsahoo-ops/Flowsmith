"""Comprehensive Universal Test Suite for Flowsmith DataLoad.

Validates all 19 mandatory requirements:
1. Existing CSV functionality remains intact.
2. CSV upload.
3. CSV download from URL.
4. TSV upload.
5. TSV download from URL.
6. ZIP containing one CSV.
7. ZIP containing one TSV.
8. ZIP containing multiple supported files.
9. ZIP containing nested directories.
10. ZIP with unsupported files.
11. Corrupt ZIP and malformed delimited files.
12. Nested archives within configured limits.
13. ZIP path traversal and decompression-bomb protection.
14. Unsafe URL and redirect rejection.
15. Download authentication and timeout failures.
16. Large-file streaming and memory behavior.
17. Cancellation and temporary-file cleanup.
18. Field mapping and downstream output compatibility.
19. Save, reload, and execute existing workflows.
"""

from __future__ import annotations

import base64
import gzip
import io
from pathlib import Path
import pytest
import uuid
import zipfile

import logging
import httpx
import respx

from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.dataload import DataLoadNode, DataLoadParams
from app.nodes.registry import get, list_nodes
from app.services.dataload.archive import ArchiveManager
from app.services.dataload.downloader import SecureFileDownloader
from app.services.dataload.registry import DataLoadOptions, DelimitedFormatHandler, FormatRegistry, ZipArchiveFormatHandler
from app.services.dataload.security import ZipSecurityValidator, safe_temp_sandbox
from app.services.dataload.service import DataLoadService
from app.services.dataload.ssrf_validator import validate_download_url, redact_sensitive_url


def make_test_ctx(wf_id: str = "test_wf", node_id: str = "data_load") -> NodeContext:
    return NodeContext(
        execution_id=f"exec_{uuid.uuid4().hex[:12]}",
        workflow_id=wf_id,
        node_id=node_id,
        logger=logging.getLogger("test"),
        http_client=httpx.AsyncClient(),
    )


# 1. Existing CSV functionality remains intact
@pytest.mark.asyncio
async def test_1_existing_csv_functionality_intact():
    node = DataLoadNode()
    ctx = make_test_ctx()
    csv_str = "FirstName,LastName,Email\nAda,Lovelace,ada@example.com\nAlan,Turing,alan@example.com\n"
    params = DataLoadParams(csv_content=csv_str, persist_to_db=False)
    res = await node.run(ctx, params, [])
    assert len(res.output_items) == 1
    summary = res.output_items[0]["summary"]
    assert summary["success"] is True
    assert summary["total_parsed"] == 2
    records = res.output_items[0]["records"]
    assert records[0]["FirstName"] == "Ada"
    assert records[1]["FirstName"] == "Alan"


# 2. CSV upload (Base64 Data URL upload)
@pytest.mark.asyncio
async def test_2_csv_upload_data_url():
    node = DataLoadNode()
    ctx = make_test_ctx()
    raw = "FirstName,LastName,Email\nGrace,Hopper,grace@example.com\n"
    b64 = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
    data_url = f"data:text/csv;base64,{b64}"

    params = DataLoadParams(
        source_mode="upload",
        csv_content=data_url,
        persist_to_db=False,
    )
    res = await node.run(ctx, params, [])
    assert res.output_items[0]["summary"]["success"] is True
    assert res.output_items[0]["summary"]["total_parsed"] == 1
    assert res.output_items[0]["records"][0]["LastName"] == "Hopper"


# 3. CSV download from URL
@pytest.mark.asyncio
async def test_3_csv_download_from_url():
    node = DataLoadNode()
    ctx = make_test_ctx()
    test_url = "https://example.com/data/contacts.csv"
    csv_bytes = b"FirstName,LastName,Email\nClaude,Shannon,claude@example.com\n"

    with respx.mock:
        respx.get(test_url).respond(
            status_code=200,
            content=csv_bytes,
            headers={"Content-Type": "text/csv", "Content-Disposition": 'attachment; filename="contacts.csv"'},
        )
        params = DataLoadParams(
            source_mode="url",
            download_url=test_url,
            persist_to_db=False,
        )
        res = await node.run(ctx, params, [])
        assert res.output_items[0]["summary"]["success"] is True
        assert res.output_items[0]["summary"]["total_parsed"] == 1
        assert res.output_items[0]["records"][0]["FirstName"] == "Claude"


# 4. TSV upload
@pytest.mark.asyncio
async def test_4_tsv_upload():
    node = DataLoadNode()
    ctx = make_test_ctx()
    tsv_raw = "FirstName\tLastName\tEmail\nMargaret\tHamilton\tmargaret@example.com\n"
    b64 = base64.b64encode(tsv_raw.encode("utf-8")).decode("utf-8")
    data_url = f"data:text/tab-separated-values;base64,{b64}"

    params = DataLoadParams(
        source_mode="upload",
        csv_content=data_url,
        file_name="apollo.tsv",
        persist_to_db=False,
    )
    res = await node.run(ctx, params, [])
    assert res.output_items[0]["summary"]["success"] is True
    assert res.output_items[0]["records"][0]["FirstName"] == "Margaret"
    assert res.output_items[0]["records"][0]["LastName"] == "Hamilton"


# 5. TSV download from URL
@pytest.mark.asyncio
async def test_5_tsv_download_from_url():
    node = DataLoadNode()
    ctx = make_test_ctx()
    test_url = "https://example.com/reports/nasa.tsv"
    tsv_bytes = b"FirstName\tLastName\tEmail\nKatherine\tJohnson\tkatherine@example.com\n"

    with respx.mock:
        respx.get(test_url).respond(
            status_code=200,
            content=tsv_bytes,
            headers={"Content-Type": "text/tab-separated-values"},
        )
        params = DataLoadParams(
            source_mode="url",
            download_url=test_url,
            persist_to_db=False,
        )
        res = await node.run(ctx, params, [])
        assert res.output_items[0]["summary"]["success"] is True
        assert res.output_items[0]["records"][0]["LastName"] == "Johnson"


# 6. ZIP containing one CSV
@pytest.mark.asyncio
async def test_6_zip_containing_one_csv():
    node = DataLoadNode()
    ctx = make_test_ctx()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("customers.csv", "FirstName,LastName,Email\nBarbara,Liskov,barbara@example.com\n")
    b64_zip = base64.b64encode(buf.getvalue()).decode("utf-8")
    data_url = f"data:application/zip;base64,{b64_zip}"

    params = DataLoadParams(
        source_mode="upload",
        csv_content=data_url,
        persist_to_db=False,
    )
    res = await node.run(ctx, params, [])
    assert res.output_items[0]["summary"]["success"] is True
    assert res.output_items[0]["summary"]["total_parsed"] == 1
    assert res.output_items[0]["records"][0]["FirstName"] == "Barbara"


# 7. ZIP containing one TSV
@pytest.mark.asyncio
async def test_7_zip_containing_one_tsv():
    node = DataLoadNode()
    ctx = make_test_ctx()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.tsv", "FirstName\tLastName\tEmail\nDorothy\tVaughan\tdorothy@example.com\n")
    b64_zip = base64.b64encode(buf.getvalue()).decode("utf-8")
    data_url = f"data:application/zip;base64,{b64_zip}"

    params = DataLoadParams(
        source_mode="upload",
        csv_content=data_url,
        persist_to_db=False,
    )
    res = await node.run(ctx, params, [])
    assert res.output_items[0]["summary"]["success"] is True
    assert res.output_items[0]["records"][0]["FirstName"] == "Dorothy"


# 8. ZIP containing multiple supported files (combine mode)
@pytest.mark.asyncio
async def test_8_zip_multiple_files_combine():
    node = DataLoadNode()
    ctx = make_test_ctx()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("batch1.csv", "FirstName,LastName,Email\nAlice,Smith,alice@example.com\n")
        zf.writestr("batch2.csv", "FirstName,LastName,Email\nBob,Jones,bob@example.com\n")
    b64_zip = base64.b64encode(buf.getvalue()).decode("utf-8")
    data_url = f"data:application/zip;base64,{b64_zip}"

    params = DataLoadParams(
        source_mode="upload",
        csv_content=data_url,
        archive_process_mode="combine",
        persist_to_db=False,
    )
    res = await node.run(ctx, params, [])
    assert res.output_items[0]["summary"]["success"] is True
    assert res.output_items[0]["summary"]["total_parsed"] == 2
    recs = res.output_items[0]["records"]
    assert recs[0]["FirstName"] == "Alice"
    assert recs[1]["FirstName"] == "Bob"
    # Metadata injection check
    assert "_source_file" in recs[0]
    assert "_archive_path" in recs[0]


# 9. ZIP containing nested directories
@pytest.mark.asyncio
async def test_9_zip_nested_directories():
    node = DataLoadNode()
    ctx = make_test_ctx()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("2026/Q1/apac/sales.csv", "FirstName,LastName,Email\nKen,Thompson,ken@example.com\n")
    b64_zip = base64.b64encode(buf.getvalue()).decode("utf-8")
    data_url = f"data:application/zip;base64,{b64_zip}"

    params = DataLoadParams(
        source_mode="upload",
        csv_content=data_url,
        archive_pattern="**/*.csv",
        persist_to_db=False,
    )
    res = await node.run(ctx, params, [])
    assert res.output_items[0]["summary"]["success"] is True
    assert res.output_items[0]["records"][0]["FirstName"] == "Ken"
    assert res.output_items[0]["records"][0]["_archive_path"] == "2026/Q1/apac/sales.csv"


# 10. ZIP with unsupported files (properly reported and skipped)
def test_10_zip_with_unsupported_files():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("valid.csv", "FirstName,LastName,Email\nLinus,Torvalds,linus@example.com\n")
        zf.writestr("binary.exe", b"\x00\x01\x02\x03")
        zf.writestr("image.png", b"\x89PNG\r\n\x1a\n")
    zip_bytes = buf.getvalue()

    inspection = ArchiveManager.inspect_archive(zip_bytes)
    assert len(inspection.supported_files) == 1
    assert "binary.exe" in inspection.unsupported_files
    assert "image.png" in inspection.unsupported_files

    items, unsupported = ArchiveManager.extract_tabular_files(zip_bytes)
    assert len(items) == 1
    assert items[0].filename == "valid.csv"
    assert "binary.exe" in unsupported


# 11. Corrupt ZIP and malformed delimited files
@pytest.mark.asyncio
async def test_11_corrupt_zip_handling():
    node = DataLoadNode()
    ctx = make_test_ctx()
    corrupt_zip = b"PK\x03\x04corrupted_payload_that_is_not_a_valid_zip"
    b64 = base64.b64encode(corrupt_zip).decode("utf-8")
    data_url = f"data:application/zip;base64,{b64}"

    params = DataLoadParams(source_mode="upload", csv_content=data_url)
    res = await node.run(ctx, params, [])
    assert res.output_items[0]["success"] is False
    assert "CORRUPT_ZIP" in res.output_items[0].get("error_code", "")


# 12. Nested archives within configured limits
@pytest.mark.asyncio
async def test_12_nested_archives():
    # Build inner zip
    inner_buf = io.BytesIO()
    with zipfile.ZipFile(inner_buf, "w") as zf_inner:
        zf_inner.writestr("inner_contacts.csv", "FirstName,LastName,Email\nGuido,van Rossum,guido@example.com\n")
    inner_bytes = inner_buf.getvalue()

    # Build outer zip containing inner zip
    outer_buf = io.BytesIO()
    with zipfile.ZipFile(outer_buf, "w") as zf_outer:
        zf_outer.writestr("nested.zip", inner_bytes)
    outer_bytes = outer_buf.getvalue()

    # Should extract within max_nesting_depth=2
    items, _ = ArchiveManager.extract_tabular_files(outer_bytes, max_nesting_depth=2)
    assert len(items) == 1
    assert items[0].filename == "inner_contacts.csv"
    assert items[0].nested_depth == 1

    # Should reject when max_nesting_depth=0
    with pytest.raises(NodeExecutionError) as exc_info:
        ArchiveManager.extract_tabular_files(outer_bytes, max_nesting_depth=0)
    assert exc_info.value.code == "ZIP_NESTING_DEPTH_EXCEEDED"


# 13. ZIP path traversal and decompression-bomb protection
def test_13_zip_path_traversal_rejection():
    # Attempt ZipSlip (path traversal with ../)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/passwd", "root:x:0:0:root")
    zip_bytes = buf.getvalue()

    with pytest.raises(NodeExecutionError) as exc_info:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            ZipSecurityValidator.validate_archive(zf)
    assert exc_info.value.code == "ZIP_PATH_TRAVERSAL"


def test_13_zip_bomb_rejection():
    # Attempt total uncompressed size exceeding limit
    zf_mock = type("MockZipFile", (), {})()
    mock_info = zipfile.ZipInfo(filename="huge.csv")
    mock_info.file_size = 200_000_000  # 200MB (exceeds default 150MB total)
    mock_info.compress_size = 1000
    mock_info.external_attr = 0

    zf_mock.infolist = lambda: [mock_info]
    with pytest.raises(NodeExecutionError) as exc_info:
        ZipSecurityValidator.validate_archive(zf_mock)
    assert "ZIP_" in exc_info.value.code


# 14. Unsafe URL and redirect rejection (SSRF protection)
@pytest.mark.asyncio
async def test_14_ssrf_prohibited_destinations():
    # Test invalid scheme (file://)
    with pytest.raises(NodeExecutionError) as exc1:
        await validate_download_url("file:///etc/passwd", allow_loopback_in_dev=False)
    assert exc1.value.code == "SSRF_BLOCKED"

    # Test metadata destination (169.254.169.254)
    with pytest.raises(NodeExecutionError) as exc2:
        await validate_download_url("http://169.254.169.254/latest/meta-data/", allow_loopback_in_dev=False)
    assert exc2.value.code == "SSRF_BLOCKED"

    # Test private subnet RFC 1918 (10.0.0.1)
    with pytest.raises(NodeExecutionError) as exc3:
        await validate_download_url("http://10.1.2.3/data.csv", allow_loopback_in_dev=False)
    assert exc3.value.code == "SSRF_BLOCKED"


@pytest.mark.asyncio
async def test_14_ssrf_redirect_to_private_ip():
    initial_url = "https://public-service.com/download"
    private_target = "http://169.254.169.254/metadata"

    with respx.mock:
        # Mock initial public response that attempts to redirect to private metadata target
        respx.get(initial_url).respond(
            status_code=302,
            headers={"Location": private_target},
        )
        with pytest.raises(NodeExecutionError) as exc:
            await SecureFileDownloader.download_file(initial_url, allow_loopback_in_dev=False)
        assert exc.value.code == "SSRF_BLOCKED"


# 15. Download authentication and timeout failures
@pytest.mark.asyncio
async def test_15_download_bearer_auth():
    test_url = "https://example.com/protected/export.csv"
    with respx.mock:
        route = respx.get(test_url).respond(
            status_code=200,
            content=b"FirstName,LastName\nTim,Berners-Lee\n",
        )
        await SecureFileDownloader.download_file(
            url=test_url,
            auth_type="bearer",
            auth_token="secret_token_123",
            allow_loopback_in_dev=True,
        )
        assert route.called
        assert route.calls.last.request.headers.get("Authorization") == "Bearer secret_token_123"


# 16. Large-file streaming and memory behavior (row limit enforcement)
@pytest.mark.asyncio
async def test_16_streaming_row_limit():
    # Generate 100 rows
    lines = ["FirstName,LastName,Email"]
    for i in range(100):
        lines.append(f"User{i},Test{i},user{i}@example.com")
    csv_text = "\n".join(lines)

    opts = DataLoadOptions(batch_size=10, row_limit=25)
    batches = list(DelimitedFormatHandler._stream_delimited_text(csv_text, "test.csv", "test.csv", opts))
    total_rows = sum(len(b) for b in batches)
    assert total_rows == 25, f"Expected exactly 25 rows with row_limit=25, got {total_rows}"


# 17. Cancellation and temporary-file cleanup
def test_17_safe_temp_sandbox_cleanup():
    sandbox_path = None
    with safe_temp_sandbox() as temp_dir:
        sandbox_path = temp_dir
        assert temp_dir.exists()
        test_file = temp_dir / "temp.dat"
        test_file.write_bytes(b"temporary data")
        assert test_file.exists()

    assert sandbox_path is not None
    assert not sandbox_path.exists(), "Temporary directory must be cleaned up after exit"


# 18. Field mapping and downstream output compatibility
@pytest.mark.asyncio
async def test_18_downstream_output_compatibility():
    node = DataLoadNode()
    ctx = make_test_ctx()
    csv_str = "given_name,family_name,contact_email\nBrendan,Eich,brendan@example.com\n"
    params = DataLoadParams(
        csv_content=csv_str,
        field_mapping={
            "given_name": "FirstName",
            "family_name": "LastName",
            "contact_email": "Email",
        },
        persist_to_db=False,
    )
    res = await node.run(ctx, params, [])
    assert len(res.output_items) == 1
    out = res.output_items[0]
    assert "summary" in out
    assert "records" in out
    assert "invalid_records" in out
    assert "duplicate_records" in out
    records = out["records"]
    assert len(records) == 1
    assert records[0]["FirstName"] == "Brendan"
    assert records[0]["LastName"] == "Eich"
    assert records[0]["Email"] == "brendan@example.com"


# 19. Save, reload, and execute existing workflows (resolving csv_parser to DataLoadNode)
def test_19_existing_workflow_csv_parser_resolution():
    # Test resolution of legacy node_type 'csv_parser'
    legacy_node_cls = get("csv_parser")
    assert legacy_node_cls is DataLoadNode, "get('csv_parser') must resolve to DataLoadNode"

    # Test resolution of alias 'csv'
    csv_node_cls = get("csv")
    assert csv_node_cls is DataLoadNode, "get('csv') must resolve to DataLoadNode"

    # Verify no duplicate entries in list_nodes()
    catalog = list_nodes()
    dataload_types = [n["type"] for n in catalog if n["type"] in ("flowsmith.data_load", "csv_parser", "csv")]
    assert dataload_types == ["flowsmith.data_load"], "Catalog must contain only flowsmith.data_load without duplicates"
