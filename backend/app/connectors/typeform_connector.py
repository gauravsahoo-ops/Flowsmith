"""Typeform connector implementing the ConnectorSDK interface."""

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
from app.providers.typeform import TypeformProviderClient


class TypeformConnectorParams(BaseModel):
    operation: str = Field(default="list_forms")
    form_id: str = ""
    tag: str = ""
    url: str = ""
    secret: str = ""
    search: str = ""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)
    since: str = ""
    until: str = ""
    completed: bool = True
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)


class TypeformConnector(ConnectorSDK):
    connector_id = "typeform"
    display_name = "Typeform"
    description = "Create automated workflows for form responses, submission retrieval, and surveys via Typeform API v2."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = TypeformProviderClient()

    @property
    def node_types(self) -> list[str]:
        return ["typeform"]

    async def connect(self, config: dict[str, Any]) -> bool:
        token = str(config.get("token") or config.get("api_key") or "").strip()
        return bool(token)

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = TypeformConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Invalid Typeform payload: {exc}", retryable=False) from exc

        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get("typeform") or {}

        raw = payload or {}
        op = (operation or "").lower()
        if op in ("", "execute"):
            op = params.operation.lower()
        timeout = params.timeout_seconds

        form_id = str(raw.get("form_id") or params.form_id or "").strip()
        tag = str(raw.get("tag") or params.tag or "").strip()
        url = str(raw.get("url") or params.url or "").strip()
        secret = str(raw.get("secret") or params.secret or "").strip() or None
        search = str(raw.get("search") or params.search or "").strip() or None
        page = int(raw.get("page") or params.page)
        page_size = int(raw.get("page_size") or params.page_size)
        since = str(raw.get("since") or params.since or "").strip() or None
        until = str(raw.get("until") or params.until or "").strip() or None
        completed = raw.get("completed", params.completed)

        try:
            if op == "list_forms":
                return await self._provider.list_forms(creds, page=page, page_size=page_size, search=search, timeout=timeout)

            if op == "get_form":
                if not form_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "form_id is required for get_form.", retryable=False)
                return await self._provider.get_form(creds, form_id, timeout=timeout)

            if op == "get_responses":
                if not form_id:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "form_id is required for get_responses.", retryable=False)
                return await self._provider.get_responses(
                    creds, form_id, page_size=page_size, since=since, until=until, completed=bool(completed), timeout=timeout
                )

            if op == "create_webhook":
                if not form_id or not tag or not url:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "form_id, tag, and url are required for create_webhook.", retryable=False)
                return await self._provider.create_webhook(creds, form_id, tag=tag, url=url, secret=secret, timeout=timeout)

            if op == "delete_webhook":
                if not form_id or not tag:
                    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "form_id and tag are required for delete_webhook.", retryable=False)
                return await self._provider.delete_webhook(creds, form_id, tag=tag, timeout=timeout)

        except Exception as exc:
            from app.connectors import ConnectorError as _CE
            if isinstance(exc, _CE):
                raise
            raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f"Typeform {op} failed: {exc}", retryable=True) from exc

        raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"Unsupported Typeform operation '{operation}'.", retryable=False)
