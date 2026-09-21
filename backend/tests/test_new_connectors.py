"""Unit tests for newly added enterprise connectors (Supabase, Resend, Pinecone, Sentry, S3)."""

import pytest
from app.connectors import get_registry, ensure_builtin_connectors
from app.connectors.supabase_connector import SupabaseConnector
from app.connectors.resend_connector import ResendConnector
from app.connectors.pinecone_connector import PineconeConnector
from app.connectors.sentry_connector import SentryConnector
from app.connectors.s3_connector import S3Connector


@pytest.fixture(autouse=True)
def setup_connectors():
    ensure_builtin_connectors()


def test_supabase_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("supabase")
    assert defn is not None
    assert defn.display_name == "Supabase"
    assert "select_rows" in defn.operations
    assert "insert_row" in defn.operations
    assert "rpc_call" in defn.operations
    assert "supabase" in defn.credential_types


def test_resend_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("resend")
    assert defn is not None
    assert defn.display_name == "Resend"
    assert "send_email" in defn.operations
    assert "resend" in defn.credential_types


def test_pinecone_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("pinecone")
    assert defn is not None
    assert defn.display_name == "Pinecone"
    assert "upsert_vectors" in defn.operations
    assert "query_vectors" in defn.operations
    assert "pinecone" in defn.credential_types


def test_sentry_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("sentry")
    assert defn is not None
    assert defn.display_name == "Sentry"
    assert "list_issues" in defn.operations
    assert "resolve_issue" in defn.operations
    assert "sentry" in defn.credential_types


def test_s3_connector_registration():
    reg = get_registry()
    defn = reg.get_definition("s3")
    assert defn is not None
    assert "upload_file" in defn.operations
    assert "download_file" in defn.operations
    assert "aws_s3" in defn.credential_types


@pytest.mark.asyncio
async def test_s3_connector_operations():
    conn = S3Connector()
    await conn.connect({"access_key_id": "mock_id", "secret_access_key": "mock_secret", "bucket": "my-test-bucket"})
    
    # Upload
    res = await conn.op_execute("upload_file", {"key": "test.txt", "content": "hello world"})
    assert res["status"] == "success"
    assert res["bucket"] == "my-test-bucket"
    assert res["size_bytes"] == 11

    # Download
    res_down = await conn.op_execute("download_file", {"key": "test.txt"})
    assert res_down["status"] == "success"
    assert "https://my-test-bucket.s3.amazonaws.com/test.txt" in res_down["url"]

    # Delete
    res_del = await conn.op_execute("delete_object", {"key": "test.txt"})
    assert res_del["deleted"] is True


@pytest.mark.asyncio
async def test_supabase_connector_operations():
    from app.connectors import ConnectorError, ConnectorErrorCode

    conn = SupabaseConnector()
    assert conn.node_types == ["supabase"]

    # Health check without URL returns healthy=False
    hc = await conn.op_health_check()
    assert hc.healthy is False

    # op_execute without URL raises ConnectorError with NOT_CONFIGURED
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute("select_rows", {})
    assert exc_info.value.code == ConnectorErrorCode.NOT_CONFIGURED.value

    # Connect with config
    await conn.connect({"url": "https://example.supabase.co", "anon_key": "dummy"})
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute("unknown_operation", {})
    assert exc_info.value.code == ConnectorErrorCode.VALIDATION_FAILED.value

