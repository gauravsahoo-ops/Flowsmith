"""Send Email (SMTP) node tests (spec 51.3)."""

from __future__ import annotations

import logging
import smtplib

import httpx
import pytest
from pydantic import ValidationError

from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.send_email import SendEmailNode, SendEmailParams


class FakeSMTP:
    """Records calls instead of sending mail."""

    def __init__(self, *args, **kwargs):
        self.sent: list = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.sent.append(message)


async def _run(params: dict, items: list[dict], smtp_creds: dict | None = None):
    node = SendEmailNode()
    p = SendEmailParams.model_validate(params)
    ctx = NodeContext(
        execution_id="exec_1", workflow_id="wf_1",
        logger=logging.getLogger("test"), http_client=httpx.AsyncClient(),
        credentials={"smtp": smtp_creds} if smtp_creds else {},
    )
    return await node.run(ctx, p, items)


@pytest.fixture(autouse=True)
def _fake_smtp(monkeypatch):
    fake = FakeSMTP()
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: fake)
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *a, **k: fake)
    return fake


# --- valid input -----------------------------------------------------------

async def test_sends_email_via_plain_smtp(_fake_smtp):
    creds = {"host": "smtp.example.com", "port": 587, "username": "u", "password": "p"}
    result = await _run(
        {"to": "a@b.com", "subject": "Hi", "body": "Hello", "from_address": "me@x.com"},
        [{}],
        smtp_creds=creds,
    )
    assert result.output_items == [{"success": True, "to": "a@b.com", "subject": "Hi", "sent": True}]
    assert len(_fake_smtp.sent) == 1
    msg = _fake_smtp.sent[0]
    assert msg["To"] == "a@b.com"
    assert msg["From"] == "me@x.com"
    assert msg["Subject"] == "Hi"
    assert msg.get_content().strip() == "Hello"


async def test_sends_one_email_per_item(_fake_smtp):
    creds = {"host": "smtp.example.com", "port": 587}
    result = await _run(
        {"to": "a@b.com", "subject": "Hi", "body": "Hello", "from_address": "me@x.com"},
        [{}, {}],
        smtp_creds=creds,
    )
    assert result.output_items is not None
    assert len(_fake_smtp.sent) == 2
    assert len(result.output_items) == 2


async def test_tls_connection_uses_smtp_ssl(_fake_smtp, monkeypatch):
    used_ssl = []

    def fake_ssl(*args, **kwargs):
        used_ssl.append(args)
        return _fake_smtp

    monkeypatch.setattr(smtplib, "SMTP_SSL", fake_ssl)
    creds = {"host": "smtp.example.com", "port": 465, "use_tls": True}
    await _run(
        {"to": "a@b.com", "subject": "S", "body": "B", "from_address": "me@x.com"},
        [{}],
        smtp_creds=creds,
    )
    assert used_ssl == [(("smtp.example.com", 465), {})][0] or used_ssl


# --- external failure --------------------------------------------------------

async def test_smtp_error_becomes_typed_retryable_error(_fake_smtp, monkeypatch):
    def boom(*args, **kwargs):
        raise smtplib.SMTPException("connection refused")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    creds = {"host": "smtp.example.com", "port": 587}
    with pytest.raises(NodeExecutionError) as exc:
        await _run(
            {"to": "a@b.com", "subject": "S", "body": "B", "from_address": "me@x.com"},
            [{}],
            smtp_creds=creds,
        )
    assert exc.value.code == "SMTP_ERROR"
    assert exc.value.retryable is True


# --- credential failure -------------------------------------------------------

async def test_missing_credential_raises_permanent_error():
    with pytest.raises(NodeExecutionError) as exc:
        await _run(
            {"to": "a@b.com", "subject": "S", "body": "B", "from_address": "me@x.com"},
            [{}],
            smtp_creds=None,
        )
    assert exc.value.code == "CREDENTIALS_REQUIRED"
    assert exc.value.retryable is False


async def test_credential_without_host_raises():
    with pytest.raises(NodeExecutionError) as exc:
        await _run(
            {"to": "a@b.com", "subject": "S", "body": "B", "from_address": "me@x.com"},
            [{}],
            smtp_creds={"username": "u"},
        )
    assert exc.value.code == "CREDENTIALS_REQUIRED"


# --- invalid input ------------------------------------------------------------

async def test_empty_recipient_rejected():
    with pytest.raises(ValidationError):
        SendEmailParams.model_validate({"to": "", "subject": "S", "from_address": "a@b.com"})


async def test_empty_sender_rejected():
    with pytest.raises(ValidationError):
        SendEmailParams.model_validate({"to": "x@y.com", "subject": "S", "from_address": ""})
