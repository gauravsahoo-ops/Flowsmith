"""Gmail connector: send, search, and read mail via the Gmail API."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.connectors import (
    ConnectorSDK,
    ConnectorError,
    ConnectorCategory,
    ConnectorStatus,
    ConnectorErrorCode,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations
from app.providers.gmail import GmailProviderClient

logger = logging.getLogger(__name__)


class GmailConnectorParams(BaseModel):
    operation: str = Field(default="send")
    to: str = Field(default="", description="Comma-separated recipients.")
    cc: str = Field(default="", description="Comma-separated CC.")
    bcc: str = Field(default="", description="Comma-separated BCC.")
    subject: str = Field(default="", description="Email subject.")
    body_text: str = Field(default="", description="Body (plain text or HTML).")
    html: bool = Field(default=False, description="Treat body as HTML.")
    query: str = Field(default="", description="Gmail search query for list_messages.")
    max_results: int = Field(default=10, ge=1, le=100)
    page_token: str = ""
    message_id: str = ""
    format: str = Field(default="metadata", description="metadata | full | raw | minimal")
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)

    @field_validator("to")
    @classmethod
    def _to_required(cls, v: str) -> str:
        # Read-only operations do not require a recipient. The connector
        # validates this only when the send operation is selected.
        return v.strip()


class GmailConnector(ConnectorSDK, ConnectorOperations):
    connector_id = "gmail"
    display_name = "Gmail"
    description = "Send, search, and read Gmail messages."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GmailProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["gmail"]

    async def connect(self, config: dict[str, Any]) -> bool:
        if not config.get("refresh_token"):
            return False
        self.status = ConnectorStatus.CONNECTED
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = GmailConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid Gmail payload: {exc}",
                retryable=False,
            ) from exc

        creds = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("gmail") or {}

        op = (operation or "").lower()
        try:
            if op in ("", "execute", "send"):
                if not params.to:
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST,
                        "operation=send requires a 'to' address.",
                        retryable=False,
                    )
                return await self._provider.send(
                    creds,
                    to=params.to,
                    subject=params.subject or "(no subject)",
                    body_text=params.body_text,
                    cc=params.cc,
                    bcc=params.bcc,
                    html=params.html,
                    timeout=params.timeout_seconds,
                )
            if op == "list_messages":
                return await self._provider.list_messages(
                    creds,
                    query=params.query,
                    max_results=params.max_results,
                    page_token=params.page_token,
                    timeout=params.timeout_seconds,
                )
            if op == "get_message":
                return await self._provider.get_message(
                    creds,
                    message_id=params.message_id,
                    format=params.format,
                    timeout=params.timeout_seconds,
                )
            if op == "get_profile":
                return await self._provider.get_profile(creds, timeout=params.timeout_seconds)
            if op == "list_labels":
                return await self._provider.list_labels(creds, timeout=params.timeout_seconds)
        except ConnectorError:
            raise

        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST,
            f"Unsupported Gmail operation '{operation}'.",
            retryable=False,
        )

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "output": {
                "connector_id": self.connector_id,
                "name": self.name,
                "status": self.status,
                "metadata": self._metadata,
            },
            "success": True,
        }

    async def op_describe(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": self.to_dict(), "success": True}
