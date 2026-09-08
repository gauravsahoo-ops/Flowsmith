"""Public Salesforce Outbound Message trigger tests (Phase 10).

Mirrors the webhook trigger suite: the event enters the EXISTING
execution pipeline (webhooks table snapshot -> start_execution ->
queue -> worker). Covers ACK semantics, deduplication by MessageId,
object filtering, skip-if-running, auth/verification failures and the
audit trail. Observability ids ride in X-Flowsmith-* response headers
alongside the SOAP Ack Salesforce requires.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select

from app.db import get_session
from app.models import AuditEvent, WebhookDelivery
from tests.test_api.conftest import SLOW_TYPE, auth_headers, register

pytestmark = [pytest.mark.timing, pytest.mark.usefixtures("slow_node")]

URL = "/api/triggers/salesforce"
PATH = "sf-outbound/lead-create-9f2ac1"


def _setup(client):
    return auth_headers(register(client)["token"])


def _trigger_workflow(workflow_id="wf_sf_trigger", path=PATH, object_name="", slow=False):
    nodes = [
        {"id": "sf_trig", "type": "salesforce_trigger",
         "parameters": {"path": path, "object_name": object_name}},
        {"id": "echo", "type": "set_data",
         "parameters": {"fields": {"email": "{{ $json.record.Email }}",
                                   "object_type": "{{ $json.object_type }}"}}},
    ]
    connections = [{"source": "sf_trig", "target": "echo"}]
    if slow:
        nodes.append({"id": "slow", "type": SLOW_TYPE, "parameters": {}, "settings": {}})
        connections.append({"source": "echo", "target": "slow"})
    return {
        "id": workflow_id,
        "name": "SF Trigger",
        "nodes": nodes,
        "connections": connections,
        "settings": {},
    }


def _envelope(message_id="04lMSG000001", object_type="Lead", record_id="00QLEADID1", **fields):
    sf_fields = {"Id": record_id, **fields}
    field_xml = "".join(
        f'<sf:{k} xmlns:sf="urn:sobjects.soap.sforce.com">{v}</sf:{k}>'
        for k, v in sf_fields.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<soapenv:Header/>"
        "<soapenv:Body>"
        '<notifications xmlns="http://soap.sforce.com/2005/09/outbound">'
        "<OrganizationId>00DAuditOrg</OrganizationId>"
        "<ActionId>04kACTION</ActionId>"
        f"<MessageId>{message_id}</MessageId>"
        f'<Notification xsi:type="{object_type}Notification">'
        "<Id>04tNOTIF</Id>"
        f'<sObject xsi:type="{object_type}">{field_xml}</sObject>'
        "</Notification>"
        "</notifications>"
        "</soapenv:Body></soapenv:Envelope>"
    )


def _post(client, body, path=PATH, headers=None):
    return client.post(
        f"{URL}/{path}",
        content=body.encode() if isinstance(body, str) else body,
        headers={"Content-Type": "text/xml; charset=utf-8", **(headers or {})},
    )


def _create_and_activate(client, headers, workflow):
    client.post("/api/workflows", json=workflow, headers=headers)
    resp = client.patch(f"/api/workflows/{workflow['id']}/active", json={"active": True}, headers=headers)
    assert resp.status_code == 200, resp.text


def _poll(client, execution_id, headers, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = client.get(f"/api/executions/{execution_id}", headers=headers)
        data = resp.json()["data"]
        if data["status"] not in ("running", "queued", "cancelling"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish in time")


def _deliveries(path=PATH):
    db = get_session()
    try:
        return db.scalars(
            select(WebhookDelivery).where(WebhookDelivery.path == path)
        ).all()
    finally:
        db.close()


def test_outbound_message_fires_workflow_end_to_end(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _trigger_workflow())

    resp = _post(client, _envelope(Email="ada@example.com"))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/xml")
    assert b"<Ack>true</Ack>" in resp.content

    execution_id = resp.headers["X-Flowsmith-Execution-Id"]
    delivery_id = resp.headers["X-Flowsmith-Delivery-Id"]
    assert resp.headers["X-Flowsmith-Skipped"] == "false"

    exec_data = _poll(client, execution_id, headers)
    assert exec_data["status"] == "success"
    assert exec_data["trigger"] == "salesforce_outbound_message"
    out = exec_data["results"]["outputs"]["echo"]["main"][0]
    assert out["email"] == "ada@example.com"
    assert out["object_type"] == "Lead"

    rows = _deliveries()
    assert len(rows) == 1
    assert rows[0].id == delivery_id
    assert rows[0].status == "success"  # linked to the execution outcome
    assert rows[0].execution_id == execution_id
    assert rows[0].idempotency_key == "sf:04lMSG000001"


def test_duplicate_message_id_does_not_reexecute(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _trigger_workflow())

    first = _post(client, _envelope(message_id="04lDUP00001", Email="a@b.com"))
    assert first.status_code == 200
    exec_data = _poll(client, first.headers["X-Flowsmith-Execution-Id"], headers)
    assert exec_data["status"] == "success"

    # Salesforce's retry of the same MessageId must not re-execute...
    second = _post(client, _envelope(message_id="04lDUP00001", Email="a@b.com"))
    assert second.status_code == 200
    assert b"<Ack>true</Ack>" in second.content  # ...but still gets an Ack
    assert second.headers["X-Flowsmith-Delivery-Id"] == first.headers["X-Flowsmith-Delivery-Id"]

    # Only ONE delivery and ONE execution despite the duplicate.
    assert len(_deliveries()) == 1


def test_malformed_payload_is_rejected_with_400(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _trigger_workflow())
    assert _post(client, "<this-is-not-soap/>").status_code == 400


def test_entity_expansion_attack_is_rejected(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _trigger_workflow())
    evil = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soapenv:Body>&lol;</soapenv:Body></soapenv:Envelope>"
    )
    assert _post(client, evil).status_code == 400


def test_unknown_or_foreign_paths_404(client):
    _setup(client)
    assert _post(client, _envelope(), path="unknown/path-1").status_code == 404
    # Paths outside the reserved namespace never resolve here.
    assert _post(client, _envelope(), path="plain-hook").status_code == 404


def test_inactive_workflow_404(client):
    headers = _setup(client)
    client.post("/api/workflows", json=_trigger_workflow(), headers=headers)
    assert _post(client, _envelope()).status_code == 404


def test_non_xml_content_type_415(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _trigger_workflow())
    resp = client.post(f"{URL}/{PATH}", json={"nope": True})
    assert resp.status_code == 415


def test_object_filter_acks_but_skips_execution(client):
    headers = _setup(client)
    _create_and_activate(client, headers,
                         _trigger_workflow(object_name="Lead", workflow_id="wf_sf_filtered"))

    # A Contact notification does not match the Lead-only filter but is
    # still ACKed so Salesforce stops retrying.
    resp = _post(client, _envelope(message_id="04lFILTER01", object_type="Contact"))
    assert resp.status_code == 200
    assert b"<Ack>true</Ack>" in resp.content
    assert resp.headers["X-Flowsmith-Skipped"] == "true"

    rows = _deliveries(path=PATH)
    assert len(rows) == 1
    assert rows[0].status == "skipped"
    assert rows[0].execution_id is None

    # Matching objects still execute.
    ok_resp = _post(client, _envelope(message_id="04lFILTER02", object_type="Lead",
                                      Email="match@example.com"))
    assert ok_resp.status_code == 200
    exec_data = _poll(client, ok_resp.headers["X-Flowsmith-Execution-Id"], headers)
    assert exec_data["status"] == "success"


def test_skips_when_workflow_already_running(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _trigger_workflow(slow=True))

    first = _post(client, _envelope(message_id="04lRUN000001"))
    assert first.status_code == 200
    first_exec = first.headers["X-Flowsmith-Execution-Id"]

    second = _post(client, _envelope(message_id="04lRUN000002"))
    assert second.status_code == 200
    assert second.headers["X-Flowsmith-Skipped"] == "true"

    by_key = {r.idempotency_key: r.status for r in _deliveries()}
    assert by_key["sf:04lRUN000001"] in ("queued", "running", "success")
    assert by_key["sf:04lRUN000002"] == "skipped"

    _poll(client, first_exec, headers)  # let the first run finish cleanly


def test_generic_webhook_endpoint_cannot_claim_sf_paths(client):
    """A plain webhook node using the reserved namespace is never
    registered, so neither endpoint serves that path."""
    headers = _setup(client)
    wf = {
        "id": "wf_bad_hook",
        "name": "Bad Hook",
        "nodes": [
            {"id": "h", "type": "webhook", "parameters": {"path": PATH, "method": "POST"}},
        ],
        "connections": [],
        "settings": {},
    }
    _create_and_activate(client, headers, wf)
    # Generic route cannot match multi-segment paths...
    assert client.post("/api/webhooks/sf-outbound/lead-create-9f2ac1", json={}).status_code in (404, 405)
    # ...and the sync guard skipped the reserved path entirely.
    assert len(_deliveries()) == 0
    assert _post(client, _envelope()).status_code == 404


def test_audit_trail_records_receipt_and_rejection(client):
    headers = _setup(client)
    _create_and_activate(client, headers, _trigger_workflow())

    _post(client, _envelope(message_id="04lAUDIT001"))

    events: list[AuditEvent] = []
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        db = get_session()
        try:
            events = db.scalars(
                select(AuditEvent).where(AuditEvent.action == "salesforce.trigger_received")
            ).all()
        finally:
            db.close()
        if events:
            break
        time.sleep(0.05)

    assert len(events) >= 1
    detail = events[-1].detail or {}
    assert detail["message_id"] == "04lAUDIT001"
    assert detail["organization_id"] == "00DAuditOrg"
    assert detail["objects"] == ["Lead"]

    # Malformed hits are audited as rejections too.
    _post(client, "<junk/>")
    db = get_session()
    try:
        rejected = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "salesforce.trigger_rejected")
        ).all()
    finally:
        db.close()
    assert len(rejected) >= 1
