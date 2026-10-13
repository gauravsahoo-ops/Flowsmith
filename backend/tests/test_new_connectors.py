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
    """S3 operations must perform genuine, SigV4-signed HTTP round-trips.

    Every assertion below is backed by a real outbound request captured by the
    mock transport — there is no code path left that returns success without one.
    """
    import respx
    import httpx

    conn = S3Connector()
    assert await conn.connect(
        {
            "access_key_id": "AKIDEXAMPLE",
            "secret_access_key": "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
            "bucket_name": "my-test-bucket",
            "region": "us-east-1",
        }
    ) is True

    with respx.mock:
        upload_route = respx.put(
            "https://my-test-bucket.s3.amazonaws.com/test.txt"
        ).mock(return_value=httpx.Response(200, headers={"ETag": '"abc123"'}))
        download_route = respx.get(
            "https://my-test-bucket.s3.amazonaws.com/test.txt"
        ).mock(
            return_value=httpx.Response(
                200,
                content=b"hello world",
                headers={"Content-Type": "text/plain", "ETag": '"abc123"'},
            )
        )
        delete_route = respx.delete(
            "https://my-test-bucket.s3.amazonaws.com/test.txt"
        ).mock(return_value=httpx.Response(204))
        list_route = respx.get(
            "https://my-test-bucket.s3.amazonaws.com/"
        ).mock(
            return_value=httpx.Response(
                200,
                text=(
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    "<ListBucketResult>"
                    "<IsTruncated>false</IsTruncated>"
                    "<Contents><Key>test.txt</Key><Size>11</Size>"
                    "<ETag>&quot;abc123&quot;</ETag><StorageClass>STANDARD</StorageClass>"
                    "<LastModified>2026-01-01T00:00:00.000Z</LastModified></Contents>"
                    "</ListBucketResult>"
                ),
                headers={"Content-Type": "application/xml"},
            )
        )

        # Upload — must be a signed PUT with the real payload
        res = await conn.op_execute("upload_file", {"key": "test.txt", "content": "hello world"})
        assert upload_route.called
        sent_request = upload_route.calls.last.request
        assert sent_request.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
        assert "SignedHeaders=" in sent_request.headers["Authorization"]
        assert sent_request.headers["x-amz-content-sha256"] == (
            "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        )
        assert sent_request.content == b"hello world"

        item = res["output"][0]
        assert item["status"] == "uploaded"
        assert item["bucket"] == "my-test-bucket"
        assert item["key"] == "test.txt"
        assert item["size_bytes"] == 11
        assert item["etag"] == '"abc123"'

        # Download — returns the actual object body
        res_down = await conn.op_execute("download_file", {"key": "test.txt"})
        assert download_route.called
        assert download_route.calls.last.request.headers["Authorization"].startswith("AWS4-HMAC-SHA256")
        down = res_down["output"][0]
        assert down["status"] == "downloaded"
        assert down["content"] == "hello world"
        assert down["encoding"] == "utf-8"
        assert down["size_bytes"] == 11

        # List — parses the real ListObjectsV2 response
        res_list = await conn.op_execute("list_objects", {"prefix": ""})
        assert list_route.called
        listing = res_list["output"][0]
        assert listing["status"] == "listed"
        assert listing["count"] == 1
        assert listing["objects"][0]["key"] == "test.txt"
        assert listing["objects"][0]["size"] == 11
        assert listing["is_truncated"] is False

        # Delete — issues a signed DELETE and reflects the real status code
        res_del = await conn.op_execute("delete_object", {"key": "test.txt"})
        assert delete_route.called
        assert delete_route.calls.last.request.headers["Authorization"].startswith("AWS4-HMAC-SHA256")
        assert res_del["output"][0]["deleted"] is True
        assert res_del["output"][0]["status"] == "deleted"


@pytest.mark.asyncio
async def test_s3_connector_reports_errors_instead_of_faking_success():
    """A rejected or unissued S3 request must raise — never return success."""
    import respx
    import httpx

    from app.connectors import ConnectorError, ConnectorErrorCode

    conn = S3Connector()
    await conn.connect(
        {
            "access_key_id": "AKIDEXAMPLE",
            "secret_access_key": "secret",
            "bucket_name": "my-test-bucket",
        }
    )

    # Missing credentials -> typed NOT_CONFIGURED, no silent success
    bare = S3Connector()
    with pytest.raises(ConnectorError) as exc_info:
        await bare.op_execute("list_objects", {"bucket": "b"})
    assert exc_info.value.code == ConnectorErrorCode.NOT_CONFIGURED.value

    # Missing key -> typed BAD_REQUEST
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute("delete_object", {"key": "   "})
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value

    # Access denied by the service -> typed FORBIDDEN carrying the S3 error code
    with respx.mock:
        respx.get("https://my-test-bucket.s3.amazonaws.com/").mock(
            return_value=httpx.Response(
                403,
                text=(
                    "<Error><Code>AccessDenied</Code>"
                    "<Message>Access Denied</Message></Error>"
                ),
            )
        )
        with pytest.raises(ConnectorError) as exc_info:
            await conn.op_execute("list_objects", {})
        assert exc_info.value.code == ConnectorErrorCode.FORBIDDEN.value
        assert "AccessDenied" in str(exc_info.value)

    # Unknown operation -> typed INVALID_OPERATION
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute("definitely_not_an_op", {"key": "x"})
    assert exc_info.value.code == ConnectorErrorCode.INVALID_OPERATION.value


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

