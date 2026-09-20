"""Generated connector — do not hand-edit, regenerate from the OpenAPI spec.

Source API: Open-Meteo Ensemble Weather Forecast API
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

from .gen_open_meteo_ensemble_provider import GeneratedProvider


class GeneratedConnectorParams(BaseModel):
    operation: str = Field(default="")
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)

    model_config = {'extra': 'allow'}


OPERATIONS = {'get_v1_ensemble': {'method': 'GET', 'path': '/v1/ensemble', 'path_params': [], 'query_params': ['latitude', 'longitude', 'hourly', 'daily', 'elevation', 'temperature_unit', 'wind_speed_unit', 'precipitation_unit', 'timeformat', 'timezone', 'past_days', 'forecast_days', 'past_hours', 'forecast_hours', 'start_date', 'end_date', 'tilt', 'azimuth', 'cell_selection', 'apikey', 'models', 'temporal_resolution'], 'has_body': False}}


class GeneratedOpenMeteoEnsembleConnector(ConnectorSDK):
    connector_id = "open_meteo_ensemble"
    display_name = "Open-Meteo ensemble"
    description = "Generated from Open-Meteo Ensemble Weather Forecast API."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GeneratedProvider()

    @property
    def node_types(self) -> list[str]:
        return ["open_meteo_ensemble"]

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
            creds = context['credentials'].get("open_meteo_ensemble") or {}
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
