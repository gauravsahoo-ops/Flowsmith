"""Zoho CRM connector implementing the ConnectorSDK interface."""

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
from app.providers.zoho_crm import ZohoCrmProviderClient


class ZohoCrmConnectorParams(BaseModel):
    operation: str = Field(default="list_records")
    module: str = "Leads"
    record_id: str = ""
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=200)
    criteria: str = ""
    word: str = ""
    email: str = ""
    data: list[dict[str, Any]] | None = None
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class ZohoCrmConnector(ConnectorSDK):
    connector_id = "zoho_crm"
    display_name = "Zoho CRM"
    description = "Read, insert, update, and search leads and deals in Zoho CRM."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = ZohoCrmProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["zoho_crm"]

    async def connect(self, config: dict[str, Any]) -> bool:
        token = str(config.get("access_token") or config.get("token") or "").strip()
        return bool(token)

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = ZohoCrmConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Zoho CRM payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("zoho_crm") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        module = str(raw.get("module") or params.module or "Leads").strip()
        record_id = str(raw.get("record_id") or params.record_id or "").strip()
        page = int(raw.get("page") or params.page)
        per_page = int(raw.get("per_page") or params.per_page)
        criteria = str(raw.get("criteria") or params.criteria or "").strip() or None
        word = str(raw.get("word") or params.word or "").strip() or None
        email = str(raw.get("email") or params.email or "").strip() or None
        data = raw.get("data") or params.data or []

        try:
            if op == "list_records":
                return await self._provider.list_records(creds, module=module, page=page, per_page=per_page, timeout=timeout)

            if op == "get_record":
                if not record_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "record_id is required.", retryable=False)
                return await self._provider.get_record(creds, module, record_id, timeout=timeout)

            if op == "create_records":
                if not data:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "data array is required.", retryable=False)
                return await self._provider.create_records(creds, module, data, timeout=timeout)

            if op == "update_records":
                if not data:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "data array is required.", retryable=False)
                return await self._provider.update_records(creds, module, data, timeout=timeout)

            if op == "search_records":
                return await self._provider.search_records(creds, module, criteria=criteria, word=word, email=email, timeout=timeout)

        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Zoho CRM {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Zoho CRM operation '{operation}'.", retryable=False)
