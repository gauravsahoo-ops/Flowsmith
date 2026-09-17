"""FTP provider + node tests (stdlib ftplib, faked at the class boundary)."""

from __future__ import annotations

import ftplib
import io
from unittest.mock import patch

import httpx
import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.engine.node_base import NodeContext
from app.nodes.ftp import FtpNode, FtpParams
from app.providers.ftp import FtpSession

CREDS = {"host": "ftp.example.com", "port": 21, "username": "u", "password": "p"}


class FakeFTP:
    instances: list["FakeFTP"] = []
    mlsd_entries = [("a.txt", {"type": "file", "size": "3", "modify": "20240101120000"})]
    files = {"a.txt": b"abc"}

    def __init__(self, *args, **kwargs):
        self.calls: list = []
        FakeFTP.instances.append(self)

    def connect(self, host, port, timeout=None):
        self.calls.append(("connect", host, port))

    def login(self, user, passwd):
        self.calls.append(("login", user))

    def quit(self):
        self.calls.append(("quit",))

    def close(self):
        pass

    def mlsd(self, path):
        self.calls.append(("mlsd", path))
        return list(FakeFTP.mlsd_entries)

    def retrlines(self, cmd, callback):
        self.calls.append(("retrlines", cmd))
        for name in ("b.txt",):
            callback(name)

    def retrbinary(self, cmd, callback):
        self.calls.append(("retrbinary", cmd))
        name = cmd.split(" ", 1)[1]
        if name not in FakeFTP.files:
            raise ftplib.error_perm("550 not found")
        callback(FakeFTP.files[name])

    def storbinary(self, cmd, fp):
        self.calls.append(("storbinary", cmd))
        FakeFTP.files[cmd.split(" ", 1)[1]] = fp.read()

    def delete(self, path):
        self.calls.append(("delete", path))
        if path not in FakeFTP.files:
            raise ftplib.error_perm("550 not found")

    def mkd(self, path):
        self.calls.append(("mkd", path))
        return path


@pytest.fixture(autouse=True)
def _fake_ftp():
    FakeFTP.instances.clear()
    FakeFTP.files = {"a.txt": b"abc"}
    FakeFTP.mlsd_entries = [("a.txt", {"type": "file", "size": "3", "modify": "20240101120000"})]
    with patch.object(ftplib, "FTP", FakeFTP):
        yield


def _ctx(creds=CREDS):
    return NodeContext(
        execution_id="test", workflow_id="wf", logger=None,
        http_client=httpx.AsyncClient(), credentials={"ftp": creds},
    )


def test_list_uses_mlsd_facts():
    with FtpSession(CREDS) as session:
        entries = session.list("/docs", limit=10)
    assert entries == [{"name": "a.txt", "type": "file", "size": "3", "modify": "20240101120000"}]
    assert ("mlsd", "/docs") in FakeFTP.instances[-1].calls


def test_list_falls_back_to_nlst():
    class NoMlsd(FakeFTP):
        def mlsd(self, path):
            raise ftplib.error_perm("500 unknown")

    with patch.object(ftplib, "FTP", NoMlsd):
        with FtpSession(CREDS) as session:
            entries = session.list("/docs")
    assert entries == [{"name": "b.txt", "type": "unknown", "size": None, "modify": None}]


def test_download_and_cap():
    with FtpSession(CREDS) as session:
        assert session.download_text("a.txt") == "abc"
    with FtpSession(CREDS) as session:
        with pytest.raises(ConnectorError):
            session.download_text("a.txt", max_bytes=2)


def test_upload_delete_mkdir_shapes():
    with FtpSession(CREDS) as session:
        assert session.upload_text("/n.txt", "hi") == {"ok": True, "path": "/n.txt", "bytes": 2}
        assert session.delete("/n.txt") == {"ok": True, "path": "/n.txt"}
        assert session.mkdir("/new") == {"ok": True, "path": "/new"}


def test_missing_host_is_not_configured():
    with pytest.raises(ConnectorError) as exc_info:
        FtpSession({})
    assert exc_info.value.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)


@pytest.mark.asyncio
async def test_node_list_op():
    node = FtpNode()
    result = await node.run(_ctx(), FtpParams(operation="list", path="/docs"), [])
    assert result.output_items[0]["entries"][0]["name"] == "a.txt"


@pytest.mark.asyncio
async def test_node_requires_credential():
    from app.engine.errors import NodeExecutionError

    node = FtpNode()
    ctx = _ctx(creds=None)
    with pytest.raises(NodeExecutionError) as exc_info:
        await node.run(ctx, FtpParams(operation="list"), [])
    assert exc_info.value.code == "CREDENTIALS_REQUIRED"


def test_ftp_registered():
    from app.nodes.registry import get

    assert get("ftp") is FtpNode
