"""Generated connector — do not hand-edit, regenerate from the OpenAPI spec.

Source API: PokéAPI
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

from gen_poke_api_provider import GeneratedProvider


class GeneratedConnectorParams(BaseModel):
    operation: str = Field(default="")
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)

    model_config = {'extra': 'allow'}


OPERATIONS = {'pokemon_color_list': {'method': 'GET', 'path': '/api/v2/pokemon-color/', 'path_params': [], 'query_params': ['limit', 'offset', 'q'], 'has_body': False}, 'pokemon_color_retrieve': {'method': 'GET', 'path': '/api/v2/pokemon-color/{id}/', 'path_params': ['id'], 'query_params': [], 'has_body': False}, 'pokemon_encounters_list': {'method': 'GET', 'path': '/api/v2/pokemon/{pokemon_id}/encounters', 'path_params': ['pokemon_id'], 'query_params': [], 'has_body': False}, 'pokemon_form_list': {'method': 'GET', 'path': '/api/v2/pokemon-form/', 'path_params': [], 'query_params': ['limit', 'offset', 'q'], 'has_body': False}, 'pokemon_form_retrieve': {'method': 'GET', 'path': '/api/v2/pokemon-form/{id}/', 'path_params': ['id'], 'query_params': [], 'has_body': False}, 'pokemon_habitat_list': {'method': 'GET', 'path': '/api/v2/pokemon-habitat/', 'path_params': [], 'query_params': ['limit', 'offset', 'q'], 'has_body': False}, 'pokemon_habitat_retrieve': {'method': 'GET', 'path': '/api/v2/pokemon-habitat/{id}/', 'path_params': ['id'], 'query_params': [], 'has_body': False}, 'pokemon_list': {'method': 'GET', 'path': '/api/v2/pokemon/', 'path_params': [], 'query_params': ['limit', 'offset', 'q'], 'has_body': False}, 'pokemon_retrieve': {'method': 'GET', 'path': '/api/v2/pokemon/{id}/', 'path_params': ['id'], 'query_params': [], 'has_body': False}, 'pokemon_shape_list': {'method': 'GET', 'path': '/api/v2/pokemon-shape/', 'path_params': [], 'query_params': ['limit', 'offset', 'q'], 'has_body': False}, 'pokemon_shape_retrieve': {'method': 'GET', 'path': '/api/v2/pokemon-shape/{id}/', 'path_params': ['id'], 'query_params': [], 'has_body': False}, 'pokemon_species_list': {'method': 'GET', 'path': '/api/v2/pokemon-species/', 'path_params': [], 'query_params': ['limit', 'offset', 'q'], 'has_body': False}, 'pokemon_species_retrieve': {'method': 'GET', 'path': '/api/v2/pokemon-species/{id}/', 'path_params': ['id'], 'query_params': [], 'has_body': False}}


class GeneratedPokeApiConnector(ConnectorSDK):
    connector_id = "poke_api"
    display_name = "PokeAPI"
    description = "Generated from Pok\u00e9API."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GeneratedProvider()

    @property
    def node_types(self) -> list[str]:
        return ["poke_api"]

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
            creds = context['credentials'].get("poke_api") or {}
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
