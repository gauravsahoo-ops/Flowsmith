"""ActiveCampaign connector implementing the ConnectorSDK interface."""

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
from app.providers.activecampaign import ActiveCampaignProviderClient


class ActiveCampaignConnectorParams(BaseModel):
    operation: str = Field(default="list_contacts")
    contact_id: str = ""
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    search: str = ""
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class ActiveCampaignConnector(ConnectorSDK):
    connector_id = "activecampaign"
    display_name = "ActiveCampaign"
    description = "Create contacts, track email campaigns, and automate marketing workflows with ActiveCampaign."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = ActiveCampaignProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["activecampaign"]

    async def connect(self, config: dict[str, Any]) -> bool:
        account = str(config.get("account") or "").strip()
        token = str(config.get("api_key") or config.get("token") or "").strip()
        return bool(account and token)

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = ActiveCampaignConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid ActiveCampaign payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("activecampaign") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        contact_id = str(raw.get("contact_id") or params.contact_id or "").strip()
        email = str(raw.get("email") or params.email or "").strip()
        first_name = str(raw.get("first_name") or params.first_name or "").strip() or None
        last_name = str(raw.get("last_name") or params.last_name or "").strip() or None
        phone = str(raw.get("phone") or params.phone or "").strip() or None
        search = str(raw.get("search") or params.search or "").strip() or None
        limit = int(raw.get("limit") or params.limit)
        offset = int(raw.get("offset") or params.offset)

        try:
            if op == "list_contacts":
                return await self._provider.list_contacts(creds, limit=limit, offset=offset, search=search, timeout=timeout)

            if op == "get_contact":
                if not contact_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "contact_id is required.", retryable=False)
                return await self._provider.get_contact(creds, contact_id, timeout=timeout)

            if op == "create_contact":
                if not email:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "email is required.", retryable=False)
                return await self._provider.create_contact(creds, email, first_name=first_name, last_name=last_name, phone=phone, timeout=timeout)

            if op == "list_lists":
                return await self._provider.list_lists(creds, limit=limit, offset=offset, timeout=timeout)

            if op == "list_campaigns":
                return await self._provider.list_campaigns(creds, limit=limit, offset=offset, timeout=timeout)

        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"ActiveCampaign {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported ActiveCampaign operation '{operation}'.", retryable=False)
