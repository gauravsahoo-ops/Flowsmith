"""Workflow import/export tests (native round-trip + n8n JSON)."""

from __future__ import annotations

from tests.test_api.conftest import auth_headers, make_workflow, register


def _setup(client):
    return auth_headers(register(client)["token"])


def _n8n_doc(name="n8n Import"):
    return {
        "name": name,
        "nodes": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "name": "When clicking",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [0, 0],
                "parameters": {},
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "name": "Set",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.4,
                "position": [240, 0],
                "parameters": {
                    "assignments": [
                        {"id": "a1", "name": "greeting", "value": "hello", "type": "string"},
                    ]
                },
            },
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "name": "If",
                "type": "n8n-nodes-base.if",
                "typeVersion": 2,
                "position": [480, 0],
                "parameters": {
                    "conditions": {
                        "options": {},
                        "conditions": [
                            {
                                "id": "c1",
                                "leftValue": "={{ $json.greeting }}",
                                "rightValue": "hello",
                                "operator": "string:equals",
                            }
                        ],
                    }
                },
            },
        ],
        "connections": {
            "11111111-1111-1111-1111-111111111111": {
                "main": [[{"node": "22222222-2222-2222-2222-222222222222", "type": "main", "index": 0}]]
            },
            "22222222-2222-2222-2222-222222222222": {
                "main": [[{"node": "33333333-3333-3333-3333-333333333333", "type": "main", "index": 0}]]
            },
            "33333333-3333-3333-3333-333333333333": {
                "true": [[{"node": "44444444-4444-4444-4444-444444444444", "type": "main", "index": 0}]],
                "false": [],
            },
        },
    }


def test_export_roundtrip(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    resp = client.get("/api/workflows/wf_1/export", headers=headers)
    assert resp.status_code == 200
    doc = resp.json()["data"]
    assert doc["format"] == "opencode-workflow"
    assert doc["workflow"]["name"] == "My Workflow"
    assert doc["workflow"]["id"] == "wf_1"
    assert [n["type"] for n in doc["workflow"]["nodes"]] == ["manual_trigger", "set_data"]

    imported = client.post("/api/workflows/import", json=doc, headers=headers)
    assert imported.status_code == 201
    data = imported.json()["data"]
    assert data["id"].startswith("wf_import_")  # original id taken -> fresh id
    assert imported.json()["meta"]["source_id"] == "wf_1"


def test_import_native_document_creates_workflow(client):
    headers = _setup(client)
    resp = client.post("/api/workflows/import", json=make_workflow("wf_native"), headers=headers)
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["id"] == "wf_native"
    assert data["version"] == 1
    assert client.get("/api/workflows/wf_native", headers=headers).status_code == 200


def test_import_conflicting_id_gets_fresh_id(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    resp = client.post("/api/workflows/import", json=make_workflow(), headers=headers)
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["id"] != "wf_1"
    assert data["id"].startswith("wf_import_")
    assert resp.json()["meta"]["source_id"] == "wf_1"


def test_import_n8n_document_converts(client):
    headers = _setup(client)
    resp = client.post("/api/workflows/import", json=_n8n_doc(), headers=headers)
    assert resp.status_code == 201, resp.text
    wf = resp.json()["data"]
    assert wf["name"] == "n8n Import"
    assert wf["id"].startswith("wf_import_")

    types = {n["id"]: n["type"] for n in wf["nodes"]}
    assert types == {"n1": "manual_trigger", "n2": "set_data", "n3": "if_condition"}
    set_node = next(n for n in wf["nodes"] if n["id"] == "n2")
    assert set_node["parameters"]["fields"] == {"greeting": "hello"}
    if_node = next(n for n in wf["nodes"] if n["id"] == "n3")
    assert if_node["parameters"]["condition"] == {
        "left": "={{ $json.greeting }}",
        "operator": "equals",
        "right": "hello",
    }
    assert if_node["position"] == {"x": 480, "y": 0}

    conns = wf["connections"]
    edge_map = {c["source"]: c["target"] for c in conns}
    assert edge_map.get("n1") == "n2"
    assert edge_map.get("n2") == "n3"
    true_edge = [c for c in conns if c["source"] == "n3" and c["sourceHandle"] == "true"]
    assert len(true_edge) == 0  # dangling n8n branch (unknown target) dropped
    assert not any(c["source"] == "n3" for c in conns)


def test_import_n8n_unknown_node_type_rejected(client):
    headers = _setup(client)
    doc = _n8n_doc()
    doc["nodes"].append(
        {
            "id": "99999999-9999-9999-9999-999999999999",
            "name": "Fancy",
            "type": "n8n-nodes-base.slack",
            "typeVersion": 2,
            "position": [900, 0],
            "parameters": {},
        }
    )
    resp = client.post("/api/workflows/import", json=doc, headers=headers)
    assert resp.status_code == 422
    assert "n8n-nodes-base.slack" in resp.json()["detail"]


def test_import_garbage_rejected(client):
    headers = _setup(client)
    assert client.post("/api/workflows/import", json={"foo": 1}, headers=headers).status_code == 422
    assert client.post("/api/workflows/import", json=[1, 2], headers=headers).status_code == 422


def test_export_requires_auth(client):
    assert client.get("/api/workflows/x/export").status_code == 401
    assert client.post("/api/workflows/import", json={}).status_code == 401