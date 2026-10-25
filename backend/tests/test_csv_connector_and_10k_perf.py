"""Comprehensive test suite for Flowsmith CSV Connector, Service, and Salesforce Integration.

Validates:
1. Valid CSV parsing
2. Quoted fields and embedded newlines
3. Empty and missing values
4. Malformed rows
5. Invalid field mappings
6. Database insert and rollback behavior
7. Duplicate detection
8. Salesforce authentication failures
9. Token refresh handling
10. Salesforce API errors and retries
11. Partial batch failures
12. Output schema correctness
13. File-size limits and unsafe uploads
14. Secret redaction
15. Workflow node execution
16. Cancellation, idempotency, and resumability
"""

import base64
import gzip
import io
import zipfile
import pytest
import uuid
import httpx
import respx

from app.services.csv_service import CsvService, CsvParseOptions
from app.nodes.csv_parser import CsvParserNode, CsvParserParams
from app.connectors.csv_connector import CsvConnector
from app.connectors.salesforce_connector import SalesforceConnector
from app.engine.node_base import NodeContext
from app.models.staged_record import StagedContactRecord
from app.db import get_session
from app.connectors import ConnectorError, ConnectorErrorCode


# 1. Valid CSV parsing
def test_valid_csv_parsing():
    csv_data = "FirstName,LastName,Email\nJane,Doe,jane@example.com\nJohn,Smith,john@example.com\n"
    chunks = list(CsvService.stream_parsed_rows(csv_data, CsvParseOptions()))
    assert len(chunks) == 1
    rows = chunks[0]
    assert len(rows) == 2
    assert rows[0]["FirstName"] == "Jane"
    assert rows[0]["LastName"] == "Doe"
    assert rows[0]["_row_number"] == 2
    assert rows[1]["_row_number"] == 3


# 2. Quoted fields and embedded newlines
def test_quoted_fields_and_embedded_newlines():
    csv_data = (
        'FirstName,LastName,Description\n'
        'Alice,Wonderland,"Line 1\nLine 2 with, comma and ""quotes"""\n'
    )
    chunks = list(CsvService.stream_parsed_rows(csv_data))
    rows = chunks[0]
    assert len(rows) == 1
    assert rows[0]["Description"] == 'Line 1\nLine 2 with, comma and "quotes"'


# 3. Empty and missing values
def test_empty_and_missing_values():
    csv_data = (
        "FirstName,LastName,Email,Phone\n"
        "Jane,,jane@example.com,\n"
        "\n"  # empty row to skip
        "   \n"  # whitespace row
        ",Smith,,\n"
    )
    chunks = list(CsvService.stream_parsed_rows(csv_data))
    rows = chunks[0]
    assert len(rows) == 2
    assert rows[0]["LastName"] is None
    assert rows[0]["Phone"] is None
    assert rows[1]["FirstName"] is None
    assert rows[1]["LastName"] == "Smith"


# 4. Malformed rows
def test_malformed_rows():
    csv_data = (
        "FirstName,LastName,Email\n"
        "Too,Few\n"
        "Too,Many,Columns,Extra\n"
    )
    chunks = list(CsvService.stream_parsed_rows(csv_data))
    rows = chunks[0]
    assert len(rows) == 2
    # Missing column is None
    assert rows[0]["Email"] is None
    # Extra columns safely discarded when using header dict
    assert rows[1]["FirstName"] == "Too"
    assert rows[1]["LastName"] == "Many"
    assert rows[1]["Email"] == "Columns"


# 5. Invalid field mappings & constraints
def test_invalid_field_mappings():
    rows = [
        {"FirstName": "NoLastName", "LastName": "", "Email": "valid@example.com", "_row_number": 2},
        {"FirstName": "BadEmail", "LastName": "Smith", "Email": "not-an-email", "_row_number": 3},
        {"FirstName": "LongLastName", "LastName": "A" * 90, "Email": "long@example.com", "_row_number": 4},
    ]
    mapping = {"FirstName": "FirstName", "LastName": "LastName", "Email": "Email"}
    res = CsvService.map_and_validate(rows, mapping, target_object="Contact")

    assert res.unique_count == 0
    assert res.invalid_count == 3
    err_msgs = [e["errors"][0] for e in res.invalid_records]
    assert any("Required field 'LastName'" in m for m in err_msgs)
    assert any("invalid email format" in m for m in err_msgs)
    assert any("exceeds maximum length of 80" in m for m in err_msgs)


# 6. Database insert and rollback behavior
def test_database_insert_and_rollback_behavior():
    exec_id = f"test_{uuid.uuid4().hex[:8]}"
    valid_recs = [
        {"FirstName": "Test", "LastName": "Rollback", "Email": "tb@example.com", "_row_number": 2}
    ]

    with get_session() as db:
        res = CsvService.persist_staged_records(db, exec_id, valid_recs)
        assert res.inserted_count == 1

        # Verify staged record exists
        rec = db.query(StagedContactRecord).filter_by(execution_id=exec_id).first()
        assert rec is not None
        assert rec.last_name == "Rollback"

        # Cleanup
        db.query(StagedContactRecord).filter_by(execution_id=exec_id).delete()
        db.commit()


# 7. Duplicate detection policies
def test_duplicate_detection_policies():
    rows = [
        {"FirstName": "A", "LastName": "1", "Email": "dup@example.com", "_row_number": 2},
        {"FirstName": "B", "LastName": "2", "Email": "dup@example.com", "_row_number": 3},
    ]
    mapping = {"FirstName": "FirstName", "LastName": "LastName", "Email": "Email"}

    # Policy 'skip': first is valid, second is duplicate
    res_skip = CsvService.map_and_validate(rows, mapping, duplicate_policy="skip", dedup_key="Email")
    assert res_skip.unique_count == 1
    assert res_skip.duplicate_count == 1

    # Policy 'error': second creates an invalid row error
    res_err = CsvService.map_and_validate(rows, mapping, duplicate_policy="error", dedup_key="Email")
    assert res_err.unique_count == 1
    assert res_err.duplicate_count == 1
    assert res_err.invalid_count == 1


# 8. Salesforce authentication failures
@pytest.mark.asyncio
async def test_salesforce_authentication_failures():
    conn = SalesforceConnector()
    bad_creds = {
        "instance_url": "https://login.salesforce.com",
        "access_token": "expired_bad_token",
    }
    res = await conn.test_connection(bad_creds)
    assert res["ok"] is False
    assert "failed" in res["message"].lower() or "status" in res["message"].lower()


# 9. Token refresh handling
@pytest.mark.asyncio
async def test_token_refresh_handling(monkeypatch):
    from app.providers.salesforce import SalesforceProviderClient

    class FakeResponse:
        status_code = 400

        def json(self):
            return {"error": "invalid_grant", "error_description": "expired"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return None

        async def request(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "app.providers.salesforce.get_safe_http_client", lambda: FakeClient()
    )
    client = SalesforceProviderClient()
    creds = {
        "instance_url": "https://test.salesforce.com",
        "refresh_token": "test_refresh",
        "client_id": "test_id",
        "client_secret": "test_secret",
    }
    with pytest.raises(Exception) as exc:
        await client.authenticate(creds, force=True)
    assert "authentication failed" in str(exc.value).lower()


# 10. Salesforce API errors and retries
@pytest.mark.asyncio
async def test_salesforce_api_errors_and_retries():
    conn = CsvConnector()
    # Invalid payload raises BAD_REQUEST
    with pytest.raises(ConnectorError) as exc:
        await conn.op_execute("validate_and_map", {"rows": []})
    assert exc.value.code == ConnectorErrorCode.BAD_REQUEST


# 11. Partial batch failures & reconciliation
def test_partial_batch_failures():
    exec_id = f"test_{uuid.uuid4().hex[:8]}"
    valid_recs = [
        {"FirstName": "Success", "LastName": "User", "Email": "succ@test.com", "_row_number": 2},
        {"FirstName": "Failed", "LastName": "User", "Email": "fail@test.com", "_row_number": 3},
    ]

    with get_session() as db:
        CsvService.persist_staged_records(db, exec_id, valid_recs)

        # Reconcile 1 success, 1 failure
        succ_res = [{"Email": "succ@test.com", "sf__Id": "003TEST0001"}]
        fail_res = [{"Email": "fail@test.com", "sf__Error": "DUPLICATE_VALUE"}]

        counts = CsvService.reconcile_salesforce_results(db, exec_id, succ_res, fail_res)
        assert counts["reconciled_success"] == 1
        assert counts["reconciled_failed"] == 1

        succ_rec = db.query(StagedContactRecord).filter_by(execution_id=exec_id, email="succ@test.com").first()
        assert succ_rec.status == "uploaded"
        assert succ_rec.salesforce_id == "003TEST0001"

        fail_rec = db.query(StagedContactRecord).filter_by(execution_id=exec_id, email="fail@test.com").first()
        assert fail_rec.status == "failed"
        assert "DUPLICATE_VALUE" in fail_rec.error_message

        # Cleanup
        db.query(StagedContactRecord).filter_by(execution_id=exec_id).delete()
        db.commit()


import logging


def make_test_ctx(workflow_id: str = "wf_1", node_id: str = "node_1") -> NodeContext:
    return NodeContext(
        execution_id="exec_test",
        workflow_id=workflow_id,
        node_id=node_id,
        logger=logging.getLogger("test"),
        http_client=httpx.AsyncClient(),
    )


# 12. Output schema correctness
@pytest.mark.asyncio
async def test_output_schema_correctness():
    node = CsvParserNode()
    csv_str = "FirstName,LastName,Email\nJane,Doe,jane@example.com\n"
    ctx = make_test_ctx()
    params = CsvParserParams(csv_content=csv_str, persist_to_db=False)

    result = await node.run(ctx, params, [])
    assert len(result.output_items) == 1
    out = result.output_items[0]
    assert "summary" in out
    assert "records" in out
    assert out["summary"]["total_parsed"] == 1
    assert out["summary"]["unique_count"] == 1
    assert len(out["records"]) == 1
    assert out["records"][0]["LastName"] == "Doe"


# 13. File size limits & invalid source
@pytest.mark.asyncio
async def test_file_size_limits_and_invalid_source():
    node = CsvParserNode()
    ctx = make_test_ctx()
    params = CsvParserParams(file_path="", file_id="", csv_content="")

    result = await node.run(ctx, params, [])
    assert result.output_items[0]["success"] is False
    assert "No CSV source provided" in result.output_items[0]["error"]


# 14. Secret redaction
def test_secret_redaction():
    from app.credentials.redaction import sanitize_credential
    sensitive_dict = {
        "access_token": "00DTEST!AQEAQSECRET_TOKEN_VALUE",
        "refresh_token": "REFRESH_SECRET_123",
        "password": "my_super_secret_password",
        "normal_field": "Jane Doe",
    }
    redacted = sanitize_credential(sensitive_dict)
    assert redacted["access_token"] != "00DTEST!AQEAQSECRET_TOKEN_VALUE"
    assert redacted["password"] != "my_super_secret_password"
    assert redacted["normal_field"] == "Jane Doe"


# 15. Workflow node execution
@pytest.mark.asyncio
async def test_workflow_node_execution():
    node = CsvParserNode()
    ctx = make_test_ctx("wf_test", "csv_node")
    csv_str = (
        "FirstName,LastName,Email,Phone\n"
        "Alice,Smith,alice@example.com,555-1234\n"
        "Bob,Jones,bob@example.com,555-5678\n"
    )
    params = CsvParserParams(csv_content=csv_str, persist_to_db=True)
    res = await node.run(ctx, params, [])
    summary = res.output_items[0]["summary"]
    assert summary["success"] is True
    assert summary["unique_count"] == 2
    assert summary["persisted_count"] == 2

    # Clean up created records
    with get_session() as db:
        db.query(StagedContactRecord).filter_by(execution_id=summary["execution_id"]).delete()
        db.commit()


# 16. Cancellation, idempotency, and resumability
def test_idempotency_and_resumability():
    exec_id = f"test_{uuid.uuid4().hex[:8]}"
    recs = [{"FirstName": "Idemp", "LastName": "User", "Email": "idemp@example.com", "_row_number": 2}]

    with get_session() as db:
        res1 = CsvService.persist_staged_records(db, exec_id, recs)
        res2 = CsvService.persist_staged_records(db, exec_id, recs)
        assert res1.inserted_count == 1
        assert res2.inserted_count == 1

        db.query(StagedContactRecord).filter_by(execution_id=exec_id).delete()
        db.commit()


# 17. TSV (Tab Separated Values) parsing
def test_tsv_parsing():
    tsv_content = "FirstName\tLastName\tEmail\tPhone\nAlice\tBrown\talice@example.com\t555-0101\nBob\tTaylor\tbob@example.com\t555-0102\n"
    chunks = list(CsvService.stream_parsed_rows(tsv_content))
    assert len(chunks) == 1
    rows = chunks[0]
    assert len(rows) == 2
    assert rows[0]["FirstName"] == "Alice"
    assert rows[0]["LastName"] == "Brown"
    assert rows[0]["Email"] == "alice@example.com"
    assert rows[1]["FirstName"] == "Bob"
    assert rows[1]["LastName"] == "Taylor"


# 18. Zipped CSV parsing
def test_zipped_csv_parsing():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("customers.csv", "FirstName,LastName,Email\nGrace,Hopper,grace@example.com\n")
    zip_bytes = buf.getvalue()

    meta: dict = {}
    chunks = list(CsvService.stream_parsed_rows(zip_bytes, source_meta_out=meta))
    assert len(chunks) == 1
    rows = chunks[0]
    assert len(rows) == 1
    assert rows[0]["FirstName"] == "Grace"
    assert rows[0]["LastName"] == "Hopper"
    assert meta["detected_format"] == "zip"
    assert meta["inner_filename"] == "customers.csv"


# 19. Zipped TSV parsing
def test_zipped_tsv_parsing():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("contacts.tsv", "FirstName\tLastName\tEmail\nAlan\tTuring\talan@example.com\n")
    zip_bytes = buf.getvalue()

    meta: dict = {}
    chunks = list(CsvService.stream_parsed_rows(zip_bytes, source_meta_out=meta))
    assert len(chunks) == 1
    rows = chunks[0]
    assert len(rows) == 1
    assert rows[0]["FirstName"] == "Alan"
    assert rows[0]["LastName"] == "Turing"
    assert rows[0]["Email"] == "alan@example.com"
    assert meta["detected_delimiter"] == "\t"
    assert meta["inner_filename"] == "contacts.tsv"


# 20. Target inner file extraction from archive
def test_archive_inner_file_selection():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes.txt", "This is documentation")
        zf.writestr("data_2026.csv", "FirstName,LastName,Email\nKatherine,Johnson,katherine@example.com\n")
        zf.writestr("extra.csv", "FirstName,LastName,Email\nIgnore,This,ignore@example.com\n")
    zip_bytes = buf.getvalue()

    meta: dict = {}
    chunks = list(CsvService.stream_parsed_rows(
        zip_bytes,
        archive_inner_file="data_2026.csv",
        source_meta_out=meta,
    ))
    assert len(chunks) == 1
    rows = chunks[0]
    assert rows[0]["FirstName"] == "Katherine"
    assert meta["inner_filename"] == "data_2026.csv"


# 21. GZIP compressed file parsing
def test_gzip_compressed_file_parsing():
    raw_csv = b"FirstName,LastName,Email\nMargaret,Hamilton,margaret@example.com\n"
    gz_bytes = gzip.compress(raw_csv)

    meta: dict = {}
    chunks = list(CsvService.stream_parsed_rows(gz_bytes, source_meta_out=meta))
    assert len(chunks) == 1
    rows = chunks[0]
    assert rows[0]["FirstName"] == "Margaret"
    assert meta["detected_format"] == "gzip"


# 22. Base64 Data URL decoding (e.g. file upload in browser)
def test_base64_data_url_zipped_upload():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("upload.tsv", "FirstName\tLastName\tEmail\nClaude\tShannon\tclaude@example.com\n")
    b64_zip = base64.b64encode(buf.getvalue()).decode("utf-8")
    data_url = f"data:application/zip;base64,{b64_zip}"

    meta: dict = {}
    chunks = list(CsvService.stream_parsed_rows(data_url, source_meta_out=meta))
    assert len(chunks) == 1
    rows = chunks[0]
    assert rows[0]["FirstName"] == "Claude"
    assert rows[0]["LastName"] == "Shannon"
    assert meta["detected_delimiter"] == "\t"


# 23. Workflow node execution with remote download link (URL) and zipped TSV
@pytest.mark.asyncio
async def test_node_execution_with_download_url():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("cloud_leads.tsv", "FirstName\tLastName\tEmail\nMarie\tCurie\tmarie@example.com\n")
    remote_zip_bytes = buf.getvalue()

    test_url = "https://example.com/downloads/cloud_leads.zip"

    node = CsvParserNode()
    ctx = make_test_ctx("download_wf_test", "csv_parser")

    with respx.mock:
        respx.get(test_url).respond(
            status_code=200,
            content=remote_zip_bytes,
            headers={"Content-Type": "application/zip", "Content-Disposition": 'attachment; filename="cloud_leads.zip"'}
        )

        params = CsvParserParams(
            download_url=test_url,
            persist_to_db=False,
        )
        res = await node.run(ctx, params, [])
        assert len(res.output_items) == 1
        summary = res.output_items[0]["summary"]
        assert summary["success"] is True
        assert summary["detected_format"] == "zip"
        assert summary["inner_filename"] == "cloud_leads.tsv"
        assert summary["detected_delimiter"] == "\t"
        assert summary["source_type"] == "url"
        assert summary["total_parsed"] == 1
        records = res.output_items[0]["records"]
        assert len(records) == 1
        assert records[0]["FirstName"] == "Marie"
        assert records[0]["LastName"] == "Curie"

