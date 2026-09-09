"""Public form trigger tests (Batch D): definition, submit-to-execution,
field validation, 404s, activation semantics. Mirrors the webhook suite.
"""

from __future__ import annotations

import time

import pytest

from app.db import get_session
from app.models import WebhookTrigger
from tests.test_api.conftest import auth_headers, register

pytestmark = [pytest.mark.timing]

FORM_PATH = "form/contact-abcdefgh12345678"

FIELDS = [
    {"name": "name", "type": "text", "required": True, "label": "Name"},
    {"name": "age", "type": "number", "required": False, "label": "Age"},
    {"name": "newsletter", "type": "boolean", "required": False, "label": "Newsletter"},
]


def _setup(client):
    return auth_headers(register(client)["token"])


def _form_workflow(workflow_id="wf_form"):
    return {
        "id": workflow_id,
        "name": "FormFlow",
        "nodes": [
            {"id": "trigger", "type": "form_trigger",
             "parameters": {"path": FORM_PATH, "title": "Contact", "fields": FIELDS}},
            {"id": "echo", "type": "set_data",
             "parameters": {"fields": {"who": "{{ $json.form.name }}"}}},
        ],
        "connections": [{"source": "trigger", "target": "echo"}],
        "settings": {},
    }


def _create_and_activate(client, headers, workflow):
    client.post("/api/workflows", json=workflow, headers=headers)
    resp = client.patch(f"/api/workflows/{workflow['id']}/active", json={"active": True}, headers=headers)
    assert resp.status_code == 200, resp.text


def _poll(client, execution_id, headers, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = client.get(f"/api/executions/{execution_id}", headers=headers)
        status = resp.json()["data"]["status"]
        if status not in ("running", "queued", "cancelling"):
            return resp.json()["data"]
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish in time")


def test_form_definition_public(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _form_workflow())
    resp = client.get(f"/api/webhooks/{FORM_PATH}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["title"] == "Contact"
    assert [f["name"] for f in data["fields"]] == ["name", "age", "newsletter"]


def test_form_submit_fires_workflow(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _form_workflow())
    resp = client.post(f"/api/webhooks/{FORM_PATH}", json={"name": "Ada", "age": "36"})
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert data["skipped"] is False
    exec_data = _poll(client, data["execution_id"], headers)
    assert exec_data["status"] == "success"
    assert exec_data["results"]["outputs"]["echo"]["main"][0]["who"] == "Ada"
    trig_out = exec_data["results"]["outputs"]["trigger"]["main"][0]
    assert trig_out["form"] == {"name": "Ada", "age": 36}


def test_form_missing_required_422(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _form_workflow())
    assert client.post(f"/api/webhooks/{FORM_PATH}", json={"age": 3}).status_code == 422


def test_form_unknown_slug_404(client):
    assert client.get("/api/webhooks/form/nope-abcdefgh12345678").status_code == 404
    assert client.post("/api/webhooks/form/nope-abcdefgh12345678", json={}).status_code == 404


def test_form_inactive_workflow_404(client):
    headers = _setup(client)
    client.post("/api/workflows", json=_form_workflow(), headers=headers)
    assert client.post(f"/api/webhooks/{FORM_PATH}", json={"name": "x"}).status_code == 404


def test_form_deactivate_removes_definition(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _form_workflow())
    assert client.get(f"/api/webhooks/{FORM_PATH}").status_code == 200
    client.patch("/api/workflows/wf_form/active", json={"active": False}, headers=headers)
    assert client.get(f"/api/webhooks/{FORM_PATH}").status_code == 404
    assert client.post(f"/api/webhooks/{FORM_PATH}", json={"name": "x"}).status_code == 404

    db = get_session()
    try:
        assert db.query(WebhookTrigger).count() == 0
    finally:
        db.close()
