"""OpenAPI emitter + discovery tests (Phase 1): no network, tmp dirs."""

from __future__ import annotations

import asyncio

from app.connectors.openapi_emit import (
    connector_key_for,
    discover_generated,
    emit_connector_files,
)
from app.connectors.openapi_import import parse_spec
from tests.test_api.test_openapi_import import SAMPLE


def test_connector_key_for():
    assert connector_key_for("Widget API") == "widget_api"
    assert connector_key_for("9lives!") == "gen_9lives"
    assert connector_key_for("") == "gen_api"
    assert len(connector_key_for("x" * 100)) <= 48


def test_emit_compiles_and_discovers(tmp_path):
    from app.connectors.registry import ConnectorRegistry, validate_definition

    api = parse_spec(SAMPLE)
    files = emit_connector_files("Widget API", "Widgets", api)
    assert set(files) == {"gen_widget_api_provider.py", "gen_widget_api_definition.py", "gen_widget_api_connector.py"}
    for source in files.values():
        compile(source, "<generated>", "exec")
    for name, source in files.items():
        (tmp_path / name).write_text(source, encoding="utf-8")
    pairs = discover_generated(str(tmp_path))
    assert len(pairs) == 1
    instance, definition = pairs[0]
    validate_definition(definition)  # must not raise
    assert definition.connector_key == "widget_api"
    assert set(definition.operations) == {"getwidget", "delete_widgets_widget_id", "createwidget"}
    assert definition.operations["createwidget"].credential_require == "widget_api"
    assert instance.connector_id == "widget_api"
    assert "widget_api" in instance.node_types


def test_emit_no_auth_compiles_and_validates(tmp_path):
    from app.connectors.openapi_import import ApiAuth, ApiSpec
    from app.connectors.registry import validate_definition

    api = ApiSpec(
        title="Open API", base_url="https://api.open.example",
        operations=parse_spec(SAMPLE).operations, auth=ApiAuth(kind="none"),
    )
    files = emit_connector_files("Open API", "Open", api)
    for source in files.values():
        compile(source, "<generated-noauth>", "exec")
    for name, source in files.items():
        (tmp_path / name).write_text(source, encoding="utf-8")
    pairs = discover_generated(str(tmp_path))
    assert len(pairs) == 1
    _, definition = pairs[0]
    validate_definition(definition)
    assert definition.credential_types == {}
    assert all(op.credential_require is None for op in definition.operations.values())


def test_generated_op_execute_rejects_unknown_without_network():
    import pathlib
    import tempfile

    from app.connectors import ConnectorErrorCode

    api = parse_spec(SAMPLE)
    files = emit_connector_files("Widget API", "Widgets", api)
    with tempfile.TemporaryDirectory() as tmp:
        for name, source in files.items():
            (pathlib.Path(tmp) / name).write_text(source, encoding="utf-8")
        (instance, _) = discover_generated(tmp)[0]
        try:
            asyncio.new_event_loop().run_until_complete(
                instance.op_execute("nope", {"operation": "nope"}, {"credentials": {}})
            )
            raise AssertionError("expected ConnectorError")
        except Exception as exc:
            assert getattr(exc, "code", "") == ConnectorErrorCode.BAD_REQUEST.value


def test_provider_auth_parts_without_network(tmp_path):
    import importlib.util

    from app.connectors import ConnectorErrorCode

    api = parse_spec(SAMPLE)
    files = emit_connector_files("Widget API", "Widgets", api)
    provider_file = tmp_path / "gen_widget_api_provider.py"
    provider_file.write_text(files["gen_widget_api_provider.py"], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("gen_widget_api_provider_test", provider_file)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    headers, query = module._auth_parts({"api_key": "sekret"})
    assert headers == {"X-Token": "sekret"} and query == {}
    try:
        module._auth_parts({})
        raise AssertionError("expected ConnectorError")
    except Exception as exc:
        assert getattr(exc, "code", "") == ConnectorErrorCode.NOT_CONFIGURED.value


def test_discovery_skips_incomplete_triple(tmp_path):
    (tmp_path / "gen_lonely_connector.py").write_text("x = 1\n")
    assert discover_generated(str(tmp_path)) == []


def test_register_generated_counts(tmp_path):
    from app.connectors.registry import ConnectorRegistry

    api = parse_spec(SAMPLE)
    for name, source in emit_connector_files("Widget API", "Widgets", api).items():
        (tmp_path / name).write_text(source, encoding="utf-8")
    from app.connectors.openapi_emit import register_generated

    registry = ConnectorRegistry()
    registry.initialize()
    assert register_generated(registry, str(tmp_path)) == 1
    assert registry.get("widget_api") is not None


def test_startup_registration_picks_up_generated_dir(tmp_path):
    from app.connectors import get_registry, register_builtin_connectors

    api = parse_spec(SAMPLE)
    from app.connectors.openapi_emit import emit_connector_files

    for name, source in emit_connector_files("Widget API", "Widgets", api).items():
        (tmp_path / name).write_text(source, encoding="utf-8")
    register_builtin_connectors(generated_dir=str(tmp_path))
    registry = get_registry()
    assert registry.get("widget_api") is not None
    assert registry.get("slack") is not None  # builtins unaffected
