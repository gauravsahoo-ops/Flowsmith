"""Generated connector — do not hand-edit, regenerate from the OpenAPI spec.

Source API: Frankfurter API
"""

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

from .gen_frankfurter_provider import GeneratedProvider


class GeneratedConnectorParams(BaseModel):
    operation: str = Field(default="")
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)

    model_config = {'extra': 'allow'}


OPERATIONS = {'get_currencies': {'method': 'GET', 'path': '/currencies', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_date': {'method': 'GET', 'path': '/{date}', 'path_params': ['date'], 'query_params': [], 'has_body': False}, 'get_latest': {'method': 'GET', 'path': '/latest', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_start_date': {'method': 'GET', 'path': '/{start_date}..', 'path_params': ['start_date'], 'query_params': [], 'has_body': False}, 'get_start_date_end_date': {'method': 'GET', 'path': '/{start_date}..{end_date}', 'path_params': ['start_date', 'end_date'], 'query_params': [], 'has_body': False}}


class GeneratedFrankfurterConnector(ConnectorSDK):
    connector_id = "frankfurter"
    display_name = "Frankfurter FX"
    description = "Generated from Frankfurter API."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GeneratedProvider()

    @property
    def node_types(self) -> list[str]:
        return ["frankfurter"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = GeneratedConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f'Invalid payload: {exc}', retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get('credentials'):
            creds = context['credentials'].get("frankfurter") or {}
        raw = payload or {}
        op = (operation or '').lower()
        if op in ('', 'execute'):
            op = str(params.operation or '').lower()
        meta = OPERATIONS.get(op)
        if meta is None:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f'Unsupported operation {operation!r}.', retryable=False)
        path_values = {k: raw.get(k, '') for k in meta['path_params']}
        query = {k: raw[k] for k in meta['query_params'] if raw.get(k) not in (None, '')}
        body = raw.get('body') if meta['has_body'] else None
        result = await self._provider.call(
            creds, meta['method'], meta['path'], path_values, query, body,
            timeout=params.timeout_seconds, what=op,
        )
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return {'items': result}
        return {'result': result}

    async def op_list(self, payload=None, context=None):
        return {'output': {'connector_id': self.connector_id, 'operations': sorted(OPERATIONS)}}
