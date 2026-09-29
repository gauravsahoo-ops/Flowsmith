"""DocuSign connector implementing the ConnectorSDK interface."""

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
from app.providers.docusign import DocuSignProviderClient


class DocuSignConnectorParams(BaseModel):
    operation: str = Field(default="list_envelopes")
    envelope_id: str = ""
    email_subject: str = ""
    status: str = "sent"
    from_date: str = ""
    count: int = Field(default=25, ge=1, le=100)
    recipients: dict[str, Any] | None = None
    documents: list[dict[str, Any]] | None = None
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class DocuSignConnector(ConnectorSDK):
    connector_id = "docusign"
    display_name = "DocuSign"
    description = "Create, send, and monitor eSignature envelopes and templates with DocuSign."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = DocuSignProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["docusign"]

    async def connect(self, config: dict[str, Any]) -> bool:
        account_id = str(config.get("account_id") or "").strip()
        token = str(config.get("access_token") or config.get("token") or "").strip()
        return bool(account_id and token)

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = DocuSignConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid DocuSign payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("docusign") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        envelope_id = str(raw.get("envelope_id") or params.envelope_id or "").strip()
        email_subject = str(raw.get("email_subject") or params.email_subject or "").strip()
        status = str(raw.get("status") or params.status or "sent").strip()
        from_date = str(raw.get("from_date") or params.from_date or "").strip()
        count = int(raw.get("count") or params.count)
        recipients = raw.get("recipients") or params.recipients or {}
        documents = raw.get("documents") or params.documents or []

        try:
            if op == "create_envelope":
                if not email_subject:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "email_subject is required.", retryable=False)
                return await self._provider.create_envelope(creds, email_subject, recipients, documents, status=status, timeout=timeout)

            if op == "get_envelope":
                if not envelope_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "envelope_id is required.", retryable=False)
                return await self._provider.get_envelope(creds, envelope_id, timeout=timeout)

            if op == "list_envelopes":
                if not from_date:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "from_date is required.", retryable=False)
                status_filter = str(raw.get("status") or "").strip() or None
                return await self._provider.list_envelopes(creds, from_date, count=count, status=status_filter, timeout=timeout)

            if op == "list_templates":
                return await self._provider.list_templates(creds, count=count, timeout=timeout)

        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"DocuSign {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported DocuSign operation '{operation}'.", retryable=False)
