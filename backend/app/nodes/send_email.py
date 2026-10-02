"""Send Email (SMTP) node (spec 7, node #6).

Sends one email per incoming item. SMTP connection settings come from
an "smtp" credential resolved by the engine (encrypted storage lands in
M6); the node only reads them from the context.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Any

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import NON_IDEMPOTENT, BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class SendEmailParams(BaseModel):
    to: str = Field(min_length=1, description="Recipient address.")
    subject: str = Field(min_length=1)
    body: str = ""
    from_address: str = Field(min_length=1, description="Sender address.")
    use_html: bool = False
    idempotency_key: str | None = Field(
        default=None, description="Key for tracking deduplication (node is non-idempotent)"
    )


@register
class SendEmailNode(BaseNode[SendEmailParams]):
    node_type = "send_email"
    display_name = "Send Email"
    version = 1
    description = "Sends an email via SMTP."
    category = "Communication"
    icon = "send_email"
    parameters_schema = SendEmailParams
    credential_types = ["smtp"]
    # Every run sends a real email (spec 35).
    idempotency = NON_IDEMPOTENT

    async def run(
        self,
        ctx: NodeContext,
        params: SendEmailParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        creds = ctx.credentials.get("smtp")
        if not creds or not creds.get("host"):
            raise NodeExecutionError(
                "This node needs an SMTP credential (host, port, username, password).",
                code="CREDENTIALS_REQUIRED", node_id="send_email", retryable=False,
            )

        output_items: list[dict[str, Any]] = []
        for item in input_items:
            message = EmailMessage()
            message["From"] = params.from_address
            message["To"] = params.to
            message["Subject"] = params.subject
            if params.use_html:
                message.set_content(params.body)
                message.add_alternative(params.body, subtype="html")
            else:
                message.set_content(params.body)

            # Attach any binary files present in item['binary']
            bin_dict = item.get("binary")
            if bin_dict and isinstance(bin_dict, dict):
                from app.engine.binary_data import get_binary_data_buffer
                for prop_name, bin_entry in bin_dict.items():
                    if isinstance(bin_entry, dict):
                        try:
                            raw_bytes = get_binary_data_buffer(bin_entry)
                            fname = bin_entry.get("fileName") or f"{prop_name}.bin"
                            mtype = bin_entry.get("mimeType", "application/octet-stream")
                            maintype, subtype = mtype.split("/", 1) if "/" in mtype else ("application", "octet-stream")
                            message.add_attachment(raw_bytes, maintype=maintype, subtype=subtype, filename=fname)
                        except Exception as e:
                            ctx.logger.warning(f"Could not attach binary property {prop_name}: {e}")

            try:
                await asyncio.to_thread(
                    _send_via_smtp,
                    creds, message,
                )
            except smtplib.SMTPException as exc:
                raise NodeExecutionError(
                    f"SMTP send failed: {exc}",
                    code="SMTP_ERROR", node_id="send_email", retryable=True,
                ) from exc

            # Store idempotency key for tracking (node is non-idempotent)
            if params.idempotency_key:
                await ctx.storage.set(
                    f"idem:{params.idempotency_key}",
                    {"status": "sent", "to": params.to, "subject": params.subject},
                    ttl=86400,
                )

            output_items.append({"success": True, "to": params.to, "subject": params.subject, "sent": True})

        return NodeResult(output_items=output_items)


def _send_via_smtp(creds: dict[str, Any], message: EmailMessage) -> None:
    host = creds["host"]
    port = int(creds.get("port", 587))
    username = creds.get("username")
    password = creds.get("password")

    if creds.get("use_tls"):
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            _login_and_send(server, username, password, message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            if creds.get("starttls"):
                server.starttls()
            _login_and_send(server, username, password, message)


def _login_and_send(server: smtplib.SMTP, username: str | None, password: str | None, message: EmailMessage) -> None:
    if username:
        server.login(username, password or "")
    server.send_message(message)
