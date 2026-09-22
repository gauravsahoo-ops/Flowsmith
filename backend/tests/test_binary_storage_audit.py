import pytest
from app.engine.binary_data import format_file_size, get_binary_data_buffer, prepare_binary_data
from app.engine.node_base import NodeContext
from app.nodes.file_io import FileIONode, FileIOParams
from app.nodes.http_request import HTTPRequestNode, HTTPRequestParams
import httpx
import logging
import tempfile
import os

def test_format_file_size():
    assert format_file_size(500) == "500 B"
    assert format_file_size(2048) == "2.0 KB"
    assert format_file_size(5 * 1024 * 1024) == "5.0 MB"
    assert format_file_size(2 * 1024 * 1024 * 1024) == "2.0 GB"

def test_prepare_and_get_binary_data():
    sample_bytes = b"Hello Flowsmith Enterprise Binary Storage!"
    meta = prepare_binary_data(sample_bytes, file_name="greeting.txt", mime_type="text/plain")

    assert meta["fileName"] == "greeting.txt"
    assert meta["fileExtension"] == "txt"
    assert meta["mimeType"] == "text/plain"
    assert meta["bytes"] == len(sample_bytes)
    assert meta["fileSize"] == f"{len(sample_bytes)} B"
    assert meta["id"].startswith("file_")
    assert meta["data"] != ""  # Base64 fallback populated for <1MB

    # Retrieve buffer back
    retrieved = get_binary_data_buffer(meta)
    assert retrieved == sample_bytes

@pytest.mark.asyncio
async def test_file_io_binary_read_and_write():
    sample_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as src_f:
        src_f.write(sample_png)
        src_path = src_f.name

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as dst_f:
        dst_path = dst_f.name

    try:
        ctx = NodeContext(
            execution_id="exec_bin",
            workflow_id="wf_bin",
            logger=logging.getLogger("test"),
            http_client=httpx.AsyncClient(),
        )

        # 1. Read binary
        node = FileIONode()
        read_params = FileIOParams(path=src_path, mode="read", binary=True, binary_property="data")
        read_res = await node.run(ctx, read_params, [{}])

        assert len(read_res.output_items) == 1
        item = read_res.output_items[0]
        assert "binary" in item
        assert "data" in item["binary"]
        bin_meta = item["binary"]["data"]
        assert bin_meta["fileName"] == os.path.basename(src_path)
        assert bin_meta["fileExtension"] == "png"
        assert bin_meta["bytes"] == len(sample_png)

        # 2. Write binary using input item's binary property
        write_params = FileIOParams(path=dst_path, mode="write", binary=True, binary_property="data")
        write_res = await node.run(ctx, write_params, [item])
        assert len(write_res.output_items) == 1
        assert write_res.output_items[0]["bytes_written"] == len(sample_png)

        # Verify destination file matches original bytes
        with open(dst_path, "rb") as f:
            written_bytes = f.read()
        assert written_bytes == sample_png
    finally:
        if os.path.exists(src_path):
            os.remove(src_path)
        if os.path.exists(dst_path):
            os.remove(dst_path)

@pytest.mark.asyncio
async def test_http_request_binary_file_format():
    class FakeBinaryHTTPClient:
        async def request(self, *args, **kwargs):
            class FakeResponse:
                status_code = 200
                reason_phrase = "OK"
                content = b"%PDF-1.4 sample pdf content for download"
                headers = {
                    "content-type": "application/pdf",
                    "content-disposition": 'attachment; filename="statement.pdf"'
                }
                history = []
                def raise_for_status(self):
                    pass
            return FakeResponse()

    ctx = NodeContext(
        execution_id="exec_http_bin",
        workflow_id="wf_http_bin",
        logger=logging.getLogger("test"),
        http_client=FakeBinaryHTTPClient(),
    )

    node = HTTPRequestNode()
    params = HTTPRequestParams(
        url="https://api.example.com/download/pdf",
        method="GET",
        response_format="file",
        binary_property="attachment",
    )

    res = await node.run(ctx, params, [{}])
    assert len(res.output_items) == 1
    item = res.output_items[0]
    assert "binary" in item
    assert "attachment" in item["binary"]
    bin_meta = item["binary"]["attachment"]
    assert bin_meta["fileName"] == "statement.pdf"
    assert bin_meta["mimeType"] == "application/pdf"
    assert bin_meta["bytes"] == len(b"%PDF-1.4 sample pdf content for download")

def test_api_view_and_download_file():
    from fastapi.testclient import TestClient
    from app.main import app
    import io

    client = TestClient(app)
    # Register/login test user
    email = "bin_test_user@example.com"
    pwd = "TestPassword123!"
    client.post("/api/auth/register", json={"email": email, "password": pwd, "name": "BinUser"})
    l_res = client.post("/api/auth/login", json={"email": email, "password": pwd})
    token = l_res.json()["data"]["token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # 1. Upload a sample file
    sample_content = b"PDF preview test document content"
    files = {"file": ("test_doc.pdf", io.BytesIO(sample_content), "application/pdf")}
    up_res = client.post("/api/files", files=files, headers=auth_headers)
    assert up_res.status_code == 201
    file_id = up_res.json()["data"]["id"]

    # 2. Test download endpoint with header auth
    dl_res = client.get(f"/api/files/{file_id}/download", headers=auth_headers)
    assert dl_res.status_code == 200
    assert dl_res.content == sample_content
    assert "attachment" in dl_res.headers.get("content-disposition", "")
    assert "application/pdf" in dl_res.headers.get("content-type", "")

    # 3. Test view endpoint (inline)
    vw_res = client.get(f"/api/files/{file_id}/view", headers=auth_headers)
    assert vw_res.status_code == 200
    assert vw_res.content == sample_content
    assert "inline" in vw_res.headers.get("content-disposition", "")
    assert "application/pdf" in vw_res.headers.get("content-type", "")

    # 4. Test view endpoint with query parameter ?token=
    vw_query_res = client.get(f"/api/files/{file_id}/view?token={token}")
    assert vw_query_res.status_code == 200
    assert vw_query_res.content == sample_content
    assert "inline" in vw_query_res.headers.get("content-disposition", "")
