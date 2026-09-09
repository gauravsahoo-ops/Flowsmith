"""OpenAPI importer parser tests (Phase 1): no network, inline specs."""

from __future__ import annotations

from app.connectors.openapi_import import detect_auth, extract_operations, load_spec, parse_spec

SAMPLE = {
    "openapi": "3.0.0",
    "info": {"title": "Widget API"},
    "servers": [{"url": "https://api.widgets.com/{version}", "variables": {"version": {"default": "v2"}}}],
    "components": {"securitySchemes": {"apiKey": {"type": "apiKey", "in": "header", "name": "X-Token"}}},
    "paths": {
        "/widgets/{widget_id}": {
            "get": {
                "operationId": "getWidget",
                "summary": "Fetch one widget",
                "parameters": [
                    {"name": "widget_id", "in": "path", "required": True},
                    {"name": "verbose", "in": "query", "required": False},
                ],
            },
            "delete": {"summary": "Remove a widget"},
        },
        "/widgets": {
            "post": {
                "operationId": "createWidget",
                "requestBody": {"content": {"application/json": {}}},
            }
        },
    },
}


def test_load_spec_json_and_yaml():
    import json

    import yaml

    assert load_spec(json.dumps(SAMPLE))["info"]["title"] == "Widget API"
    assert load_spec(yaml.safe_dump(SAMPLE))["info"]["title"] == "Widget API"
    assert load_spec(SAMPLE) is SAMPLE


def test_detect_auth_api_key_header():
    auth = detect_auth(SAMPLE)
    assert (auth.kind, auth.name) == ("api_key_header", "X-Token")


def test_detect_auth_variants():
    assert detect_auth({}) == detect_auth({})  # none
    assert detect_auth({"components": {"securitySchemes": {"b": {"type": "http", "scheme": "bearer"}}}}).kind == "bearer"
    assert detect_auth({"components": {"securitySchemes": {"b": {"type": "http", "scheme": "basic"}}}}).kind == "basic"
    assert detect_auth({"components": {"securitySchemes": {"o": {"type": "oauth2"}}}}).kind == "oauth2"
    assert detect_auth(
        {"components": {"securitySchemes": {"q": {"type": "apiKey", "in": "query", "name": "key"}}}}
    ).kind == "api_key_query"


def test_extract_operations_keys_params_body():
    ops = {o.operation_key: o for o in extract_operations(SAMPLE)}
    assert set(ops) == {"getwidget", "delete_widgets_widget_id", "createwidget"}
    get = ops["getwidget"]
    assert get.method == "GET" and get.path_params == ["widget_id"]
    assert [(p.name, p.required) for p in get.query_params] == [("verbose", False)]
    assert not get.has_body
    assert ops["createwidget"].has_body


def test_parse_spec_end_to_end():
    api = parse_spec(SAMPLE)
    assert api.title == "Widget API"
    assert api.base_url == "https://api.widgets.com/v2"
    assert len(api.operations) == 3


def test_parse_caps_operations():
    paths = {f"/r{i}": {"get": {"summary": "x"}} for i in range(80)}
    api = parse_spec({"info": {"title": "Big"}, "paths": paths})
    assert len(api.operations) == 50


SWAGGER2 = {
    "swagger": "2.0",
    "info": {"title": "Legacy API"},
    "host": "api.legacy.com",
    "basePath": "/v1",
    "schemes": ["https"],
    "paths": {
        "/items": {
            "get": {"summary": "List", "parameters": [{"name": "q", "in": "query"}]},
            "post": {"summary": "Create", "parameters": [{"name": "item", "in": "body"}]},
        },
        "/upload": {
            "post": {"summary": "Upload", "parameters": [{"name": "file", "in": "formData"}]},
        },
    },
}


def test_swagger2_base_url_and_body_detection():
    api = parse_spec(SWAGGER2)
    assert api.base_url == "https://api.legacy.com/v1"
    assert api.auth.kind == "none"
    ops = {o.operation_key: o for o in api.operations}
    assert not ops["get_items"].has_body
    assert ops["post_items"].has_body
    assert ops["post_upload"].has_body


def test_path_level_servers_fallback():
    api = parse_spec({
        "openapi": "3.1.0",
        "info": {"title": "Pathed"},
        "paths": {"/v1/forecast": {
            "servers": [{"url": "https://api.example.com"}],
            "get": {"summary": "F"},
        }},
    })
    assert api.base_url == "https://api.example.com"
