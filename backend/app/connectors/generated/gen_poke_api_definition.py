"""Generated definition — do not hand-edit, regenerate from the OpenAPI spec.

Source API: PokéAPI
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)


CONNECTOR_KEY = "poke_api"
CONNECTOR_VERSION = "1.0.0"
OPERATION_VERSION = "1.0.0"


def _operation(key, display_name, description, input_schema, *, retryable=True, idempotency='idempotent'):
    return ConnectorOperationV1(
        connector_key=CONNECTOR_KEY,
        connector_version=CONNECTOR_VERSION,
        operation_key=key,
        operation_version=OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema=input_schema,
        output_schema={"type": "object", "properties": {}},
        credential_require=None,
        retryable=retryable,
        idempotency=idempotency,
        node_types=[CONNECTOR_KEY],
    )


def _operations():
    return {
        "pokemon_color_list": _operation("pokemon_color_list", "List pokemon colors", "GET /api/v2/pokemon-color/", {"type": "object", "properties": {"limit": {"type": "string", "title": "limit"}, "offset": {"type": "string", "title": "offset"}, "q": {"type": "string", "title": "q"}}, "required": []}),
        "pokemon_color_retrieve": _operation("pokemon_color_retrieve", "Get pokemon color", "GET /api/v2/pokemon-color/{id}/", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "pokemon_encounters_list": _operation("pokemon_encounters_list", "Get pokemon encounter", "GET /api/v2/pokemon/{pokemon_id}/encounters", {"type": "object", "properties": {"pokemon_id": {"type": "string", "title": "pokemon_id"}}, "required": ["pokemon_id"]}),
        "pokemon_form_list": _operation("pokemon_form_list", "List pokemon forms", "GET /api/v2/pokemon-form/", {"type": "object", "properties": {"limit": {"type": "string", "title": "limit"}, "offset": {"type": "string", "title": "offset"}, "q": {"type": "string", "title": "q"}}, "required": []}),
        "pokemon_form_retrieve": _operation("pokemon_form_retrieve", "Get pokemon form", "GET /api/v2/pokemon-form/{id}/", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "pokemon_habitat_list": _operation("pokemon_habitat_list", "List pokemom habitas", "GET /api/v2/pokemon-habitat/", {"type": "object", "properties": {"limit": {"type": "string", "title": "limit"}, "offset": {"type": "string", "title": "offset"}, "q": {"type": "string", "title": "q"}}, "required": []}),
        "pokemon_habitat_retrieve": _operation("pokemon_habitat_retrieve", "Get pokemom habita", "GET /api/v2/pokemon-habitat/{id}/", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "pokemon_list": _operation("pokemon_list", "List pokemon", "GET /api/v2/pokemon/", {"type": "object", "properties": {"limit": {"type": "string", "title": "limit"}, "offset": {"type": "string", "title": "offset"}, "q": {"type": "string", "title": "q"}}, "required": []}),
        "pokemon_retrieve": _operation("pokemon_retrieve", "Get pokemon", "GET /api/v2/pokemon/{id}/", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "pokemon_shape_list": _operation("pokemon_shape_list", "List pokemon shapes", "GET /api/v2/pokemon-shape/", {"type": "object", "properties": {"limit": {"type": "string", "title": "limit"}, "offset": {"type": "string", "title": "offset"}, "q": {"type": "string", "title": "q"}}, "required": []}),
        "pokemon_shape_retrieve": _operation("pokemon_shape_retrieve", "Get pokemon shape", "GET /api/v2/pokemon-shape/{id}/", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "pokemon_species_list": _operation("pokemon_species_list", "List pokemon species", "GET /api/v2/pokemon-species/", {"type": "object", "properties": {"limit": {"type": "string", "title": "limit"}, "offset": {"type": "string", "title": "offset"}, "q": {"type": "string", "title": "q"}}, "required": []}),
        "pokemon_species_retrieve": _operation("pokemon_species_retrieve", "Get pokemon species", "GET /api/v2/pokemon-species/{id}/", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
    }


def build_poke_api_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CONNECTOR_KEY,
        display_name="PokeAPI",
        description="Generated from Pok\u00e9API.",
        category="developer",
        connector_version=CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=_operations(),
        triggers={},
        credential_types={},
        metadata={"source": "openapi-import", "api_title": "Pok\u00e9API"},
        icon="🧲",
    )
