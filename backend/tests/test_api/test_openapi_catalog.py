"""Generated connectors reach the UI catalogs end-to-end (Phase 1).

Generates a sample triple into a tmp dir, registers through the real
startup path, and asserts the type appears in GET /api/nodes and
GET /api/connectors. Restores the plain builtin registry afterwards
so no other suite observes generated state.
"""

from __future__ import annotations

import pytest

from app.connectors.openapi_emit import emit_connector_files
from app.connectors.openapi_import import parse_spec
from tests.test_api.conftest import auth_headers, register
from tests.test_api.test_openapi_import import SAMPLE

pytestmark = [pytest.mark.timing]


@pytest.fixture
def _generated_tree(tmp_path):
    from app.connectors import register_builtin_connectors

    api = parse_spec(SAMPLE)
    for name, source in emit_connector_files("Widget API", "Widgets", api).items():
        (tmp_path / name).write_text(source, encoding="utf-8")
    register_builtin_connectors(generated_dir=str(tmp_path))
    try:
        yield
    finally:
        register_builtin_connectors()


def test_generated_connector_in_connectors_catalog(client, _generated_tree):
    headers = auth_headers(register(client)["token"])
    body = client.get("/api/connectors", headers=headers).json()["data"]
    keys = {c.get("connector_key") for c in body}
    assert "widget_api" in keys


def test_generated_type_in_node_catalog(client, _generated_tree):
    headers = auth_headers(register(client)["token"])
    body = client.get("/api/nodes", headers=headers).json()["data"]
    types = {n.get("type") for n in body}
    assert "widget_api" in types


def test_generated_credential_type_listed(client, _generated_tree):
    headers = auth_headers(register(client)["token"])
    body = client.get("/api/connectors/widget_api/credential-types", headers=headers).json()["data"]
    types = body.get("credential_types", body)
    assert "widget_api" in types


def test_preview_openapi_endpoint(client):
    headers = auth_headers(register(client)["token"])
    res = client.post(
        "/api/connectors/preview-openapi",
        json={"spec": SAMPLE},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["title"] == "Widget API"
    assert data["operations_count"] > 0
    assert len(data["operations"]) > 0
    assert data["auth"]["kind"] in ("api_key_header", "none", "bearer")


def test_import_openapi_endpoint(client, tmp_path, monkeypatch):
    from pathlib import Path
    headers = auth_headers(register(client)["token"])
    gen_dir = Path(__file__).resolve().parents[2] / "app" / "connectors" / "generated"
    try:
        res = client.post(
            "/api/connectors/import-openapi",
            json={
                "spec": SAMPLE,
                "name": "test_sample_api",
                "title": "Test Sample API",
                "category": "api",
                "base_url": "https://api.example.com/v1",
            },
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["success"] is True
        assert data["connector_key"] == "test_sample_api"
        assert data["operations_count"] > 0
    finally:
        for f in gen_dir.glob("gen_test_sample_api_*.py"):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass


def test_hostile_docstring_fields_cannot_inject_statements():
    """CRITICAL regression: user-controlled info.title / servers.url must be
    emitted as literal data inside docstrings - a docstring breakout that put
    statements between the module docstring and the future import would be RCE
    when the generated module is imported by the runner."""
    import ast
    import copy

    spec = copy.deepcopy(SAMPLE)
    spec["info"]["title"] = 'Evil" ; __import__("os").system("id") ; x = """'
    spec["servers"][0]["url"] = 'https://evil.example/" ; import socket ; y = """'
    api = parse_spec(spec)
    files = emit_connector_files("evil_api", "Evil", api, "api")
    assert files
    for name, source in files.items():
        tree = ast.parse(source, filename=name)
        body = tree.body
        assert (
            isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ), f"{name}: module docstring must stay the first statement"
        assert (
            isinstance(body[1], ast.ImportFrom) and body[1].module == "__future__"
        ), f"{name}: injected statements between docstring and future import"
        assert not any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "system"
            for n in ast.walk(tree)
        ), f"{name}: hostile call leaked into executable code"


def test_import_openapi_ast_gate_rejects_breakout_statements(client, monkeypatch):
    """CRITICAL regression: even if a generated file smuggles statements in
    (docstring breakout), the AST preamble gate must reject it with 400."""
    from app.connectors import openapi_emit

    headers = auth_headers(register(client)["token"])

    def _hostile_files(key, display, api, category="api"):
        return {
            f"gen_{key}_node.py": (
                '"""\nHostile module.\n"""\n'
                '__import__("os").system("id")\n'
                "from __future__ import annotations\n"
            ),
        }

    monkeypatch.setattr(openapi_emit, "emit_connector_files", _hostile_files)
    res = client.post(
        "/api/connectors/import-openapi",
        json={
            "spec": SAMPLE,
            "name": "gen_evil_gate",
            "title": "Evil Gate",
            "category": "api",
            "base_url": "https://api.example.com/v1",
        },
        headers=headers,
    )
    assert res.status_code == 400, res.text


