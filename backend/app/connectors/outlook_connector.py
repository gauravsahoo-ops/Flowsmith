"""Microsoft Outlook connector implementing the ConnectorSDK interface.

Thin mapper over MicrosoftGraphProviderClient mail operations;
credentials arrive via context["credentials"]["microsoft_graph"].
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorCategory,
    ConnectorError,
    ConnectorErrorCode,
    ConnectorSDK,
    ConnectorStatus,
    make_connector_error,
)
from app.providers.microsoft_graph import MicrosoftGraphProviderClient


class OutlookConnectorParams(BaseModel):
    operation: str = Field(default="send", description="send | list_messages.")
    to: list[str] = Field(default_factory=list, description="Recipient addresses.")
    cc: list[str] = Field(default_factory=list)
    subject: str = ""
    body: str = ""
    save_to_sent: bool = True
    folder: str = "Inbox"
    top: int = Field(default=10, ge=1, le=50)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)


class OutlookConnector(ConnectorSDK):
    connector_id = "outlook"
    display_name = "Microsoft Outlook"
    description = "Send and read Outlook mail via Microsoft Graph."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = MicrosoftGraphProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["outlook"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return bool(
            str(config.get("tenant_id") or "").strip()
            and str(config.get("client_id") or "").strip()
            and str(config.get("client_secret") or "").strip()
        )

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._provider.reset()
        self._metadata.clear()

    async def op_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = OutlookConnectorParams.model_validate(payload)
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid Outlook payload: {exc}", retryable=False,
            ) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("microsoft_graph") or {}

        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()

        try:
            if op == "send":
                raw = payload or {}
                to = raw.get("to") or params.to
                cc = raw.get("cc") or params.cc
                subject = str(raw.get("subject") or params.subject)
                body = str(raw.get("body") or params.body)
                if not subject and not body:
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST, "send requires a subject or body.", retryable=False,
                    )
                return await self._provider.send_mail(
                    creds, to=[str(a) for a in to], subject=subject, body=body,
                    cc=[str(a) for a in cc] if cc else None,
                    save_to_sent=params.save_to_sent,
                    timeout=params.timeout_seconds,
                )
            if op == "list_messages":
                folder = str((payload or {}).get("folder") or params.folder)
                top_raw = (payload or {}).get("top")
                try:
                    top = int(top_raw) if top_raw is not None else params.top
                except (TypeError, ValueError) as exc:
                    raise make_connector_error(
                        ConnectorErrorCode.BAD_REQUEST, "top must be an integer.", retryable=False,
                    ) from exc
                return await self._provider.list_messages(
                    creds, folder=folder, top=top, timeout=params.timeout_seconds,
                )
        except ConnectorError:
            raise
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, f"Unsupported Outlook operation '{operation}'.", retryable=False,
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

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        try:
            token = await self._provider._get_access_token(config)
            if token:
                return {"ok": True, "message": "Successfully authenticated with Microsoft Graph API."}
            return {"ok": False, "message": "Failed to obtain access token."}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    async def op_describe(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": self.to_dict(), "success": True}
