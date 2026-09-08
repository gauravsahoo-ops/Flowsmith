"""Public deployment tests (M9): static UI serving, SPA fallback, CORS."""

from __future__ import annotations

import pytest

import app.main as main_module
from app.config import get_settings

INDEX_HTML = "<!doctype html><html><head></head><body><div id=\"root\"></div></body></html>"


@pytest.fixture
def frontend(tmp_path):
    """A fake built frontend; monkeypatch FRONTEND_DIST so the catch-all
    serves it (settings are read at import time, the path is not)."""
    (tmp_path / "index.html").write_text(INDEX_HTML)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('hi')")
    original = main_module.FRONTEND_DIST
    main_module.FRONTEND_DIST = tmp_path
    yield tmp_path
    main_module.FRONTEND_DIST = original


def test_serves_index_at_root(client, frontend):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "id=\"root\"" in resp.text


def test_spa_fallback_for_client_routes(client, frontend):
    resp = client.get("/workflows/wf_1/run")
    assert resp.status_code == 200
    assert "id=\"root\"" in resp.text


def test_serves_static_assets(client, frontend):
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert resp.text == "console.log('hi')"


def test_unknown_api_route_stays_404(client, frontend):
    assert client.get("/api/nope").status_code == 404
    assert client.get("/api/ws/nope").status_code == 404


def test_path_traversal_blocked(client, frontend):
    assert client.get("/..%2F..%2Fapp.py").status_code == 404


def test_frontend_disabled_404s(client, monkeypatch):
    monkeypatch.setattr(main_module, "FRONTEND_DIST", None)
    assert client.get("/").status_code == 404


def test_cors_headers_present(client):
    resp = client.get("/api/health", headers={"Origin": "http://example.com"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") in ("*", "http://example.com")


def test_health_reports_public_url(client):
    data = client.get("/api/health").json()["data"]
    assert "public_url" in data
    assert data["public_url"] == get_settings().public_url
