"""SSH provider + node tests (paramiko faked at the class boundary)."""

from __future__ import annotations

import base64
import hashlib
import io
import sys
from unittest.mock import patch

import httpx
import paramiko
import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.engine.node_base import NodeContext
from app.nodes.ssh import SshNode, SshParams

CREDS = {"host": "ssh.example.com", "port": 22, "username": "u", "password": "p"}


class FakeChannel:
    def __init__(self, out=b"", err=b"", code=0):
        self._out, self._err, self._code = out, err, code

    def recv_exit_status(self):
        return self._code

    def read(self):
        return self._out


class FakeStdout:
    def __init__(self, channel, out):
        self.channel = channel
        self._out = out

    def read(self):
        return self._out


class FakeSFTPHandle:
    def __init__(self, store, path, mode):
        self._store, self._path, self._mode = store, path, mode
        self._buf = io.BytesIO(store.get(path, b"") if "r" in mode else b"")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if "w" in self._mode:
            self._store[self._path] = self._buf.getvalue()
        return False

    def read(self, n=-1):
        return self._buf.read(n)

    def write(self, data):
        return self._buf.write(data)


class FakeSFTP:
    def __init__(self, store):
        self.store = store
        self.closed = False

    def open(self, path, mode):
        if "r" in mode and path not in self.store:
            raise OSError("no such file")
        return FakeSFTPHandle(self.store, path, mode)

    def close(self):
        self.closed = True


class AuthenticationExceptionFake(Exception):
    """Stands in for paramiko.AuthenticationException (name-matched mapping)."""


class FakeSSHClient:
    last: "FakeSSHClient | None" = None
    files = {"/remote/note.txt": b"hello"}
    fail_with: Exception | None = None

    def __init__(self):
        self.connect_kwargs = None
        self.policy = None
        self.loaded_system_host_keys = False
        self.loaded_host_keys = False
        self.added_host_keys: list[tuple[str, str, object]] = []
        FakeSSHClient.last = self

    def load_system_host_keys(self):
        self.loaded_system_host_keys = True

    def load_host_keys(self, path):
        self.loaded_host_keys = True

    def get_host_keys(self):
        client = self

        class _HostKeys:
            def add(self, hostname, keytype, key):
                client.added_host_keys.append((hostname, keytype, key))

        return _HostKeys()

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs
        if FakeSSHClient.fail_with is not None:
            raise FakeSSHClient.fail_with
        if kwargs.get("password") == "WRONG":
            raise AuthenticationExceptionFake("Authentication failed.")

    def exec_command(self, command, timeout=None):
        assert command == "echo hi"
        ch = FakeChannel(code=0)
        return None, FakeStdout(ch, b"hi\n"), FakeStdout(ch, b"")

    def open_sftp(self):
        return FakeSFTP(dict(FakeSSHClient.files))

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _fake_ssh():
    FakeSSHClient.last = None
    FakeSSHClient.files = {"/remote/note.txt": b"hello"}
    FakeSSHClient.fail_with = None
    with patch("paramiko.SSHClient", FakeSSHClient):
        yield


def _ctx(creds=CREDS):
    return NodeContext(
        execution_id="test", workflow_id="wf", logger=None,
        http_client=httpx.AsyncClient(), credentials={"ssh": creds},
    )


def test_exec_returns_output():
    from app.providers.ssh import SshSession

    with SshSession(CREDS) as session:
        out = session.exec("echo hi")
    assert out == {"ok": True, "exit_code": 0, "stdout": "hi\n", "stderr": ""}
    assert FakeSSHClient.last.connect_kwargs["hostname"] == "ssh.example.com"


def test_host_key_policy_is_strict_by_default():
    from app.providers.ssh import SshSession

    with SshSession(CREDS):
        pass
    assert isinstance(FakeSSHClient.last.policy, paramiko.RejectPolicy)
    assert FakeSSHClient.last.loaded_system_host_keys is True
    assert FakeSSHClient.last.loaded_host_keys is False


def test_inline_known_hosts_is_loaded():
    from app.providers.ssh import SshSession

    creds = {**CREDS, "known_hosts": "ssh.example.com ssh-ed25519 AAAA"}
    with SshSession(creds):
        pass
    assert FakeSSHClient.last.loaded_host_keys is True


def test_unknown_host_keys_are_rejected_even_with_legacy_opt_in():
    from app.providers.ssh import SshSession

    with SshSession({**CREDS, "allow_unknown_host_keys": True}):
        pass
    assert isinstance(FakeSSHClient.last.policy, paramiko.RejectPolicy)


def test_host_key_failure_is_not_retryable():
    from app.providers.ssh import SshSession

    FakeSSHClient.fail_with = paramiko.SSHException(
        "Server 'ssh.example.com' not found in known_hosts"
    )
    with pytest.raises(ConnectorError) as exc_info:
        SshSession(CREDS)
    assert exc_info.value.code in (
        ConnectorErrorCode.AUTH_FAILED,
        ConnectorErrorCode.AUTH_FAILED.value,
    )
    assert exc_info.value.retryable is False
    assert "host key verification failed" in str(exc_info.value).lower()


def test_fingerprint_policy_accepts_matching_key():
    from app.providers.ssh import SshSession

    class FakeKey:
        def asbytes(self):
            return b"host-key"

        def get_name(self):
            return "ssh-ed25519"

    expected = base64.b64encode(hashlib.sha256(b"host-key").digest()).decode().rstrip("=")
    with SshSession({**CREDS, "host_key_fingerprint": f"SHA256:{expected}"}):
        pass
    policy = FakeSSHClient.last.policy
    policy.missing_host_key(FakeSSHClient.last, "ssh.example.com", FakeKey())
    assert FakeSSHClient.last.added_host_keys[0][0] == "ssh.example.com"


def test_fingerprint_policy_rejects_mismatch():
    from app.providers.ssh import SshSession

    class FakeKey:
        def asbytes(self):
            return b"host-key"

        def get_name(self):
            return "ssh-ed25519"

    with SshSession({**CREDS, "host_key_fingerprint": "SHA256:not-the-key"}):
        pass
    policy = FakeSSHClient.last.policy
    with pytest.raises(paramiko.SSHException):
        policy.missing_host_key(FakeSSHClient.last, "ssh.example.com", FakeKey())


def test_auth_failure_maps():
    from app.providers.ssh import SshSession

    with pytest.raises(ConnectorError) as exc_info:
        with SshSession({**CREDS, "password": "WRONG"}):
            pass
    assert exc_info.value.code in (ConnectorErrorCode.AUTH_FAILED, ConnectorErrorCode.AUTH_FAILED.value)


def test_missing_auth_is_not_configured():
    from app.providers.ssh import SshSession

    with pytest.raises(ConnectorError) as exc_info:
        SshSession({"host": "h", "username": "u"})
    assert exc_info.value.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)


def test_missing_paramiko_is_clean_error():
    from app.providers.ssh import SshSession

    with patch.dict(sys.modules, {"paramiko": None}):
        with pytest.raises(ConnectorError) as exc_info:
            SshSession(CREDS)
    assert exc_info.value.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)
    assert "pip install paramiko" in str(exc_info.value)


def test_sftp_download_upload():
    from app.providers.ssh import SshSession

    with SshSession(CREDS) as session:
        assert session.download_text("/remote/note.txt") == "hello"
        assert session.upload_text("/remote/new.txt", "data")["bytes"] == 4


@pytest.mark.asyncio
async def test_node_exec_op():
    node = SshNode()
    result = await node.run(_ctx(), SshParams(operation="exec", command="echo hi"), [])
    assert result.output_items[0]["stdout"] == "hi\n"
    assert result.output_items[0]["exit_code"] == 0


@pytest.mark.asyncio
async def test_node_requires_credential():
    from app.engine.errors import NodeExecutionError

    node = SshNode()
    ctx = _ctx(creds=None)
    with pytest.raises(NodeExecutionError) as exc_info:
        await node.run(ctx, SshParams(operation="exec", command="echo hi"), [])
    assert exc_info.value.code == "CREDENTIALS_REQUIRED"


def test_ssh_registered():
    from app.nodes.registry import get

    assert get("ssh") is SshNode


def test_ssh_credential_validation():
    from app.credentials.registry import validate_data

    validated = validate_data("ssh", {"host": "h", "username": "u", "password": "p"})
    assert validated["host"] == "h"
    assert validated["allow_unknown_host_keys"] is False
    assert validated["known_hosts"] == ""
    assert validated["host_key_fingerprint"] == ""
    with pytest.raises(ValueError):
        validate_data("ssh", {"host": "h", "username": "u"})
    assert validate_data("ftp", {"host": "h"})["port"] == 21
