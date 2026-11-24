"""Authenticated in-app user manual endpoint."""

from __future__ import annotations

from tests.test_api.conftest import auth_headers, register


def test_user_manual_requires_auth(client):
    response = client.get("/api/help/user-manual")
    assert response.status_code in (401, 403)


def test_user_manual_returns_markdown_for_signed_in_users(client):
    reg = register(client)
    response = client.get("/api/help/user-manual", headers=auth_headers(reg["token"]))
    assert response.status_code == 200, response.text
    assert "text/markdown" in response.headers["content-type"]
    assert "Flowsmith" in response.text
