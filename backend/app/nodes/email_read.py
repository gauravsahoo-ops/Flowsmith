"""Read Email (IMAP) node (original implementation).

Reads messages from a mailbox with stdlib imaplib (blocking calls run
in a worker thread): unseen-only or recent-N from a folder, emitting
one item per message with from/to/subject/date/body-text. Pair with
the Schedule trigger for polling; no mailbox state is kept here.
"""

from __future__ import annotations

import asyncio
import email
import email.policy
import imaplib
from email.message import Message
from typing import Any

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

MAX_BODY_CHARS = 100_000


class EmailReadParams(BaseModel):
    folder: str = Field(default="INBOX", description="Mailbox folder to read.")
    unseen_only: bool = Field(default=True, description="Only unread messages.")
    limit: int = Field(default=10, ge=1, le=200)
    mark_seen: bool = Field(default=False, description="Flag fetched messages as seen.")
    timeout_seconds: float = Field(default=30.0, ge=5, le=120)


def _body_text(message: Message) -> str:
    """Prefer the first text/plain part; fall back to stripped text/html."""
    if message.is_multipart():
        fallback = ""
        for part in message.walk():
            if part.get_content_maintype() != "text":
                continue
            try:
                text = part.get_content()
            except Exception:
                continue
            if not isinstance(text, str):
                continue
            if part.get_content_subtype() == "plain":
                return text[:MAX_BODY_CHARS]
            if not fallback:
                fallback = text
        return fallback[:MAX_BODY_CHARS]
    try:
        content = message.get_content()
    except Exception:
        return ""
    return (content if isinstance(content, str) else "")[:MAX_BODY_CHARS]


def _parse_message(raw: bytes) -> dict[str, Any]:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    return {
        "message_id": str(message.get("Message-ID") or ""),
        "from": str(message.get("From") or ""),
        "to": str(message.get("To") or ""),
        "subject": str(message.get("Subject") or ""),
        "date": str(message.get("Date") or ""),
        "body_text": _body_text(message),
    }


def _fetch_via_imap(creds: dict[str, Any], params: EmailReadParams) -> list[dict[str, Any]]:
    host = str(creds.get("host") or "").strip()
    if not host:
        raise NodeExecutionError(
            "This node needs an IMAP credential (host, username, password).",
            code="CREDENTIALS_REQUIRED", node_id="email_read", retryable=False,
        )
    port = int(creds.get("port") or 993)
    username = str(creds.get("username") or "")
    password = str(creds.get("password") or "")
    folder = params.folder.strip() or "INBOX"
    try:
        if creds.get("use_tls", True):
            client: imaplib.IMAP4 = imaplib.IMAP4_SSL(host, port, timeout=params.timeout_seconds)
        else:
            client = imaplib.IMAP4(host, port, timeout=params.timeout_seconds)
    except (OSError, imaplib.IMAP4.error) as exc:
        raise NodeExecutionError(
            f"IMAP connection failed: {exc}",
            code="EMAIL_READ_CONNECT", node_id="email_read", retryable=True,
        ) from exc
    try:
        try:
            client.login(username, password)
        except imaplib.IMAP4.error as exc:
            raise NodeExecutionError(
                "IMAP login failed (check username/password).",
                code="EMAIL_READ_AUTH", node_id="email_read", retryable=False,
            ) from exc
        status, _ = client.select(f'"{folder}"', readonly=not params.mark_seen)
        if status != "OK":
            raise NodeExecutionError(
                f"IMAP folder '{folder}' unavailable.",
                code="EMAIL_READ_FOLDER", node_id="email_read", retryable=False,
            )
        criteria = "UNSEEN" if params.unseen_only else "ALL"
        status, data = client.search(None, criteria)
        if status != "OK":
            raise NodeExecutionError(
                "IMAP search failed.", code="EMAIL_READ_SEARCH",
                node_id="email_read", retryable=True,
            )
        ids = (data[0] or b"").split()[-params.limit :]
        items: list[dict[str, Any]] = []
        for num in ids:
            status, fetched = client.fetch(num, "(RFC822)")
            if status != "OK" or not fetched or not fetched[0]:
                continue
            raw = fetched[0][1]
            if isinstance(raw, bytes):
                items.append(_parse_message(raw))
        return items
    except NodeExecutionError:
        raise
    except (OSError, imaplib.IMAP4.error) as exc:
        raise NodeExecutionError(
            f"IMAP read failed: {exc}",
            code="EMAIL_READ_ERROR", node_id="email_read", retryable=True,
        ) from exc
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            client.logout()
        except Exception:
            pass


@register
class EmailReadNode(BaseNode[EmailReadParams]):
    node_type = "email_read"
    display_name = "Read Email"
    version = 1
    description = "Read messages from an IMAP mailbox."
    category = "Actions"
    icon = "📥"
    credential_types = ["imap"]
    parameters_schema = EmailReadParams

    async def run(
        self,
        ctx: NodeContext,
        params: EmailReadParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        creds = ctx.credentials.get("imap")
        if not creds:
            raise NodeExecutionError(
                "This node needs an IMAP credential (host, username, password).",
                code="CREDENTIALS_REQUIRED", node_id="email_read", retryable=False,
            )
        try:
            items = await asyncio.wait_for(
                asyncio.to_thread(_fetch_via_imap, creds, params),
                timeout=params.timeout_seconds + 10,
            )
        except asyncio.TimeoutError as exc:
            raise NodeExecutionError(
                "IMAP read timed out.",
                code="EMAIL_READ_TIMEOUT", node_id="email_read", retryable=True,
            ) from exc
        return NodeResult(output_items=items or [{"empty": True}])
