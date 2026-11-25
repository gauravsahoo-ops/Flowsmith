"""Authenticated in-app user manual endpoint."""

from __future__ import annotations

from tests.test_api.conftest import auth_headers, register


def test_user_manual_requires_auth(client):
    response = client.get("/api/help/user-manual")
    assert response.status_code in (401, 403)


def test_user_manual_returns_markdown_for_signed_in_users(client, monkeypatch, tmp_path):
    from app.api import help as help_api

    reg = register(client)
    headers = auth_headers(reg["token"])

    if help_api._manual_path() is not None:
        response = client.get("/api/help/user-manual", headers=headers)
        assert response.status_code == 200, response.text
        assert "text/markdown" in response.headers["content-type"]
        assert "Flowsmith" in response.text

    # When USER_MANUAL.md is omitted from a minimal container/CI checkout,
    # the endpoint must fail gracefully with 404 instead of crashing.
    monkeypatch.setattr(help_api, "_MANUAL_CANDIDATES", (tmp_path / "missing.md",))
    missing = client.get("/api/help/user-manual", headers=headers)
    assert missing.status_code == 404
