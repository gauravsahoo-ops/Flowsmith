"""Data Tables API + node tests."""

from __future__ import annotations

import uuid
import time
import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}


def register(client: TestClient):
    email = f"dt_{uuid.uuid4().hex[:8]}@example.com"
    pw = "Password123!"
    client.post("/api/auth/register", json={"email": email, "password": pw})
    resp = client.post("/api/auth/login", json={"email": email, "password": pw})
    return resp.json()["data"]


def create_org_ws(client: TestClient, headers):
    org = client.post("/api/organizations", json={"name": f"Org{uuid.uuid4().hex[:4]}"}, headers=headers).json()["data"]
    ws = client.post("/api/workspaces", json={"name": f"WS{uuid.uuid4().hex[:4]}", "organization_id": org["id"]}, headers=headers).json()["data"]
    return org["id"], ws["id"]


def test_create_list_get_update_delete_table(client):
    token = register(client)["token"]
    headers = auth_headers(token)
    _, ws_id = create_org_ws(client, headers)
    # create
    r = client.post("/api/data-tables", json={"name": "Customers", "description": "Test", "workspace_id": ws_id, "columns": [{"name": "name", "type": "string", "required": True}, {"name": "age", "type": "number"}]}, headers=headers)
    assert r.status_code == 201, r.text
    tbl = r.json()["data"]
    assert tbl["name"] == "Customers"
    assert len(tbl["columns"]) == 2
    tid = tbl["id"]
    # list
    r = client.get(f"/api/data-tables?workspace_id={ws_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["meta"]["total"] == 1
    # get
    r = client.get(f"/api/data-tables/{tid}", headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["id"] == tid
    # update
    r = client.patch(f"/api/data-tables/{tid}", json={"name": "Clients"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "Clients"
    # delete
    r = client.delete(f"/api/data-tables/{tid}", headers=headers)
    assert r.status_code == 200
    r = client.get(f"/api/data-tables/{tid}", headers=headers)
    assert r.status_code == 404


def test_column_crud_and_reorder(client):
    token = register(client)["token"]
    headers = auth_headers(token)
    _, ws_id = create_org_ws(client, headers)
    tbl = client.post("/api/data-tables", json={"name": "T1", "workspace_id": ws_id, "columns": []}, headers=headers).json()["data"]
    tid = tbl["id"]
    # create column
    r = client.post(f"/api/data-tables/{tid}/columns", json={"name": "email", "type": "string", "required": True}, headers=headers)
    assert r.status_code == 201
    col1 = r.json()["data"]
    r = client.post(f"/api/data-tables/{tid}/columns", json={"name": "age", "type": "number"}, headers=headers)
    assert r.status_code == 201
    col2 = r.json()["data"]
    # update column
    r = client.patch(f"/api/data-tables/{tid}/columns/{col1['id']}", json={"name": "email_address"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "email_address"
    # reorder
    r = client.post(f"/api/data-tables/{tid}/columns/reorder", json={"order": [col2["id"], col1["id"]]}, headers=headers)
    assert r.status_code == 200
    # delete
    r = client.delete(f"/api/data-tables/{tid}/columns/{col1['id']}", headers=headers)
    assert r.status_code == 200
    # verify
    r = client.get(f"/api/data-tables/{tid}", headers=headers)
    assert len(r.json()["data"]["columns"]) == 1


def test_row_crud_and_bulk(client):
    token = register(client)["token"]
    headers = auth_headers(token)
    _, ws_id = create_org_ws(client, headers)
    tbl = client.post("/api/data-tables", json={"name": "T2", "workspace_id": ws_id, "columns": [{"name": "name", "type": "string", "required": True}]}, headers=headers).json()["data"]
    tid = tbl["id"]
    # insert
    r = client.post(f"/api/data-tables/{tid}/rows", json={"data": {"name": "Alice"}}, headers=headers)
    assert r.status_code == 201
    rid = r.json()["data"]["id"]
    # list
    r = client.get(f"/api/data-tables/{tid}/rows", headers=headers)
    assert r.json()["meta"]["total"] == 1
    # update
    r = client.patch(f"/api/data-tables/{tid}/rows/{rid}", json={"data": {"name": "Alicia"}}, headers=headers)
    assert r.status_code == 200
    assert r.json()["data"]["data"]["name"] == "Alicia"
    # bulk insert
    r = client.post(f"/api/data-tables/{tid}/rows/bulk", json={"rows": [{"name": "Bob"}, {"name": "Carol"}]}, headers=headers)
    assert r.status_code == 201
    assert len(r.json()["data"]) == 2
    # bulk update
    rows = client.get(f"/api/data-tables/{tid}/rows", headers=headers).json()["data"]
    updates = [{"id": rows[0]["id"], "name": "Alicia2"}, {"id": rows[1]["id"], "name": "Bob2"}]
    r = client.post(f"/api/data-tables/{tid}/rows/bulk-update", json={"rows": updates}, headers=headers)
    assert r.status_code == 200
    # bulk delete
    ids = [rows[0]["id"], rows[1]["id"]]
    r = client.post(f"/api/data-tables/{tid}/rows/bulk-delete", json={"ids": ids}, headers=headers)
    assert r.status_code == 200
    r = client.get(f"/api/data-tables/{tid}/rows", headers=headers)
    assert r.json()["meta"]["total"] == 1  # one left (Carol)
    # delete single
    remaining = r.json()["data"][0]["id"]
    r = client.delete(f"/api/data-tables/{tid}/rows/{remaining}", headers=headers)
    assert r.status_code == 200
    r = client.get(f"/api/data-tables/{tid}/rows", headers=headers)
    assert r.json()["meta"]["total"] == 0


def test_pagination_filter_sort(client):
    token = register(client)["token"]
    headers = auth_headers(token)
    _, ws_id = create_org_ws(client, headers)
    tbl = client.post("/api/data-tables", json={"name": "T3", "workspace_id": ws_id, "columns": [{"name": "name", "type": "string"}, {"name": "age", "type": "number"}]}, headers=headers).json()["data"]
    tid = tbl["id"]
    # bulk insert 10 rows
    rows = [{"name": f"User{i}", "age": i} for i in range(10)]
    r = client.post(f"/api/data-tables/{tid}/rows/bulk", json={"rows": rows}, headers=headers)
    assert r.status_code == 201
    # pagination page 1 size 5
    r = client.get(f"/api/data-tables/{tid}/rows?page=1&pageSize=5", headers=headers)
    assert len(r.json()["data"]) == 5
    assert r.json()["meta"]["total"] == 10
    # search
    r = client.get(f"/api/data-tables/{tid}/rows?search=User1", headers=headers)
    # should match User1
    assert r.json()["meta"]["total"] >= 1
    # filter eq
    import json, urllib.parse
    f = urllib.parse.quote(json.dumps([{"column": "age", "op": "gt", "value": 5}]))
    r = client.get(f"/api/data-tables/{tid}/rows?filters={f}", headers=headers)
    assert r.json()["meta"]["total"] == 4  # ages 6-9
    # sort asc by age
    r = client.get(f"/api/data-tables/{tid}/rows?sort_by=age&sort_order=asc", headers=headers)
    ages = [row["data"]["age"] for row in r.json()["data"]]
    assert ages == sorted(ages)
    # sort desc
    r = client.get(f"/api/data-tables/{tid}/rows?sort_by=age&sort_order=desc", headers=headers)
    ages_desc = [row["data"]["age"] for row in r.json()["data"]]
    assert ages_desc == sorted(ages_desc, reverse=True)


def test_authorization_isolation(client):
    # user A creates table, user B cannot access
    token_a = register(client)["token"]
    headers_a = auth_headers(token_a)
    _, ws_a = create_org_ws(client, headers_a)
    tbl = client.post("/api/data-tables", json={"name": "Secret", "workspace_id": ws_a, "columns": []}, headers=headers_a).json()["data"]
    tid = tbl["id"]
    token_b = register(client)["token"]
    headers_b = auth_headers(token_b)
    r = client.get(f"/api/data-tables/{tid}", headers=headers_b)
    assert r.status_code == 404
    r = client.post(f"/api/data-tables/{tid}/rows", json={"data": {}}, headers=headers_b)
    assert r.status_code == 404
    # B creates own ws and table
    _, ws_b = create_org_ws(client, headers_b)
    r = client.post("/api/data-tables", json={"name": "Secret", "workspace_id": ws_b, "columns": []}, headers=headers_b)
    assert r.status_code == 201


def test_invalid_input_and_not_found(client):
    token = register(client)["token"]
    headers = auth_headers(token)
    _, ws_id = create_org_ws(client, headers)
    # invalid column type
    r = client.post("/api/data-tables", json={"name": "Bad", "workspace_id": ws_id, "columns": [{"name": "x", "type": "invalid"}]}, headers=headers)
    assert r.status_code == 422
    # missing required field on row
    tbl = client.post("/api/data-tables", json={"name": "Req", "workspace_id": ws_id, "columns": [{"name": "name", "type": "string", "required": True}]}, headers=headers).json()["data"]
    tid = tbl["id"]
    r = client.post(f"/api/data-tables/{tid}/rows", json={"data": {}}, headers=headers)
    assert r.status_code == 422
    # unknown column
    r = client.post(f"/api/data-tables/{tid}/rows", json={"data": {"unknown": "x"}}, headers=headers)
    assert r.status_code == 422
    # not found table
    r = client.get("/api/data-tables/dt_notexist", headers=headers)
    assert r.status_code == 404
    # not found row
    r = client.get(f"/api/data-tables/{tid}/rows/dtr_notexist", headers=headers)
    assert r.status_code == 404
    # duplicate table name
    r = client.post("/api/data-tables", json={"name": "Req", "workspace_id": ws_id, "columns": []}, headers=headers)
    assert r.status_code == 409
    # duplicate column name
    r = client.post(f"/api/data-tables/{tid}/columns", json={"name": "name", "type": "string"}, headers=headers)
    assert r.status_code == 409


def test_workflow_data_table_node(client):
    token = register(client)["token"]
    headers = auth_headers(token)
    _, ws_id = create_org_ws(client, headers)
    tbl = client.post("/api/data-tables", json={"name": "WFT", "workspace_id": ws_id, "columns": [{"name": "name", "type": "string", "required": True}, {"name": "age", "type": "number"}]}, headers=headers).json()["data"]
    tid = tbl["id"]
    # create workflow: trigger -> data_table insert -> data_table select
    wf_id = f"wf_{uuid.uuid4().hex[:8]}"
    wf = {
        "id": wf_id,
        "name": "DT WF",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "position": {"x": 0, "y": 0}, "parameters": {}},
            {"id": "dt1", "type": "data_table", "position": {"x": 100, "y": 0}, "parameters": {"table_id": tid, "operation": "insert", "row_data": {"name": "Bob", "age": 25}}},
            {"id": "dt2", "type": "data_table", "position": {"x": 200, "y": 0}, "parameters": {"table_id": tid, "operation": "select"}},
        ],
        "connections": [{"source": "trigger", "target": "dt1"}, {"source": "dt1", "target": "dt2"}],
        "settings": {}
    }
    r = client.post("/api/workflows", json=wf, headers=headers)
    assert r.status_code == 201, r.text
    r = client.post(f"/api/workflows/{wf_id}/run", json={"data": {}}, headers=headers)
    assert r.status_code == 202
    eid = r.json()["data"]["execution_id"]
    # poll
    for _ in range(20):
        r = client.get(f"/api/executions/{eid}", headers=headers)
        status = r.json()["data"]["status"]
        if status not in ("queued", "running"):
            break
        time.sleep(0.5)
    assert status == "success", r.text
    data = r.json()["data"]
    # Check insert output
    assert data["results"]["outputs"]["dt1"]["main"][0]["name"] == "Bob"
    # Select should return at least one row
    assert len(data["results"]["outputs"]["dt2"]["main"]) >= 1
    # Verify via API row list
    r = client.get(f"/api/data-tables/{tid}/rows", headers=headers)
    assert r.json()["meta"]["total"] == 1
