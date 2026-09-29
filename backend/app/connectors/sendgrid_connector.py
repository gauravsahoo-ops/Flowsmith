"""Twilio SendGrid connector implementing the ConnectorSDK interface."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorCategory,
    ConnectorErrorCode,
    ConnectorSDK,
    ConnectorStatus,
    make_connector_error,
)
from app.providers.sendgrid import SendGridProviderClient


class SendGridConnectorParams(BaseModel):
    operation: str = Field(default="send_mail")
    to_email: str = ""
    from_email: str = ""
    subject: str = ""
    content: str = ""
    is_html: bool = False
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    start_date: str = ""
    end_date: str = ""
    page_size: int = Field(default=50, ge=1, le=1000)
    page_token: str = ""
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class SendGridConnector(ConnectorSDK):
    connector_id = "sendgrid"
    display_name = "Twilio SendGrid"
    description = "Send emails, manage marketing contacts, and track delivery analytics via Twilio SendGrid API v3."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = SendGridProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["sendgrid"]

    async def connect(self, config: dict[str, Any]) -> bool:
        api_key = str(config.get("api_key") or config.get("token") or "").strip()
        return bool(api_key)

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = SendGridConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid SendGrid payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("sendgrid") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        to_email = str(raw.get("to_email") or params.to_email or "").strip()
        from_email = str(raw.get("from_email") or params.from_email or "").strip()
        subject = str(raw.get("subject") or params.subject or "").strip()
        content = str(raw.get("content") or params.content or "").strip()
        is_html = bool(raw.get("is_html", params.is_html))
        email = str(raw.get("email") or params.email or "").strip()
        first_name = str(raw.get("first_name") or params.first_name or "").strip() or None
        last_name = str(raw.get("last_name") or params.last_name or "").strip() or None
        start_date = str(raw.get("start_date") or params.start_date or "").strip()
        end_date = str(raw.get("end_date") or params.end_date or "").strip() or None
        page_size = int(raw.get("page_size") or params.page_size)
        page_token = str(raw.get("page_token") or params.page_token or "").strip() or None

        try:
            if op == "send_mail":
                if not to_email or not from_email or not subject or not content:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "to_email, from_email, subject, and content are required.", retryable=False)
                return await self._provider.send_mail(creds, to_email, from_email, subject, content, is_html=is_html, timeout=timeout)

            if op == "list_contacts":
                return await self._provider.list_contacts(creds, page_size=page_size, page_token=page_token, timeout=timeout)

            if op == "add_contact":
                if not email:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "email is required for add_contact.", retryable=False)
                return await self._provider.add_contact(creds, email, first_name=first_name, last_name=last_name, timeout=timeout)

            if op == "get_stats":
                if not start_date:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "start_date is required for get_stats.", retryable=False)
                return await self._provider.get_stats(creds, start_date, end_date=end_date, timeout=timeout)

        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"SendGrid {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported SendGrid operation '{operation}'.", retryable=False)
