"""Gmail connector (Phase 41): send email via Gmail API (send-only scope)."""

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
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)

    @field_validator("to")
    @classmethod
    def _to_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("'to' is required")
        return v


class GmailConnector(ConnectorSDK, ConnectorOperations):
    connector_id = "gmail"
    display_name = "Gmail"
    description = "Send email through Gmail (send-only scope)."
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
        if op in ("", "execute", "send"):
            try:
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
