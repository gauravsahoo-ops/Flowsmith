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


