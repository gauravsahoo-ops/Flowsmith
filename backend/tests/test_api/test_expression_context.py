"""Expression-context autocomplete endpoint (Phase 40)."""

from __future__ import annotations

import pytest

from tests.test_api.conftest import auth_headers, register


def test_expression_context_shape_and_access(client):
    headers = auth_headers(register(client)["token"])
    wf = {
        "id": "wf_exprctx",
        "name": "Expr ctx",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "http", "type": "http_request", "parameters": {}},
        ],
        "connections": [{"source": "trigger", "target": "http"}],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    body = client.get("/api/workflows/wf_exprctx/expression-context", headers=headers)
    assert body.status_code == 200
    data = body.json()["data"]
    names = {v["name"] for v in data["variables"]}
    assert {"$json", "$node.<id>.json", "$execution.id", "$workflow.id", "$now"} <= names
    node_ids = {n["id"] for n in data["nodes"]}
    assert {"trigger", "http"} <= node_ids
    assert "upper" in data["pipes"] and "typeof" in data["pipes"]


def test_expression_context_404_for_private_foreign(client):
    owner = auth_headers(register(client, email="ec-owner@x.com")["token"])
    other = auth_headers(register(client, email="ec-other@x.com")["token"])
    wf = {
        "id": "wf_ec_priv",
        "name": "Private",
        "nodes": [{"id": "t", "type": "manual_trigger", "parameters": {}}],
        "connections": [],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=owner).status_code == 201
    assert client.get(
        "/api/workflows/wf_ec_priv/expression-context", headers=other
    ).status_code == 404
