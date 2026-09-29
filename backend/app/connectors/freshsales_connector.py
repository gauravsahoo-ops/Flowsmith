"""Freshsales connector implementing the ConnectorSDK interface."""

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
from app.providers.freshsales import FreshsalesProviderClient


class FreshsalesConnectorParams(BaseModel):
    operation: str = Field(default="list_contacts")
    contact_id: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    mobile_number: str = ""
    name: str = ""
    amount: float = 0.0
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=25, ge=1, le=100)
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class FreshsalesConnector(ConnectorSDK):
    connector_id = "freshsales"
    display_name = "Freshsales"
    description = "Manage sales pipelines, deals, and customer contacts with Freshsales."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = FreshsalesProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["freshsales"]

    async def connect(self, config: dict[str, Any]) -> bool:
        domain = str(config.get("domain") or "").strip()
        token = str(config.get("api_key") or config.get("token") or "").strip()
        return bool(domain and token)

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = FreshsalesConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Freshsales payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("freshsales") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        contact_id = str(raw.get("contact_id") or params.contact_id or "").strip()
        first_name = str(raw.get("first_name") or params.first_name or "").strip()
        last_name = str(raw.get("last_name") or params.last_name or "").strip()
        email = str(raw.get("email") or params.email or "").strip()
        mobile_number = str(raw.get("mobile_number") or params.mobile_number or "").strip() or None
        name = str(raw.get("name") or params.name or "").strip()
        amount = float(raw.get("amount") or params.amount)
        page = int(raw.get("page") or params.page)
        per_page = int(raw.get("per_page") or params.per_page)

        try:
            if op == "list_contacts":
                return await self._provider.list_contacts(creds, page=page, per_page=per_page, timeout=timeout)

            if op == "get_contact":
                if not contact_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "contact_id is required.", retryable=False)
                return await self._provider.get_contact(creds, contact_id, timeout=timeout)

            if op == "create_contact":
                if not first_name or not last_name or not email:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "first_name, last_name, and email are required.", retryable=False)
                return await self._provider.create_contact(creds, first_name, last_name, email, mobile_number=mobile_number, timeout=timeout)

            if op == "list_deals":
                return await self._provider.list_deals(creds, page=page, per_page=per_page, timeout=timeout)

            if op == "create_deal":
                if not name:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "name is required for create_deal.", retryable=False)
                return await self._provider.create_deal(creds, name, amount, timeout=timeout)

        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Freshsales {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Freshsales operation '{operation}'.", retryable=False)
