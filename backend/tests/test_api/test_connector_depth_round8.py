"""Depth pass 8: DocuSign, SendGrid, Zoho CRM, PagerDuty, Intercom, and Box."""

from __future__ import annotations

import pytest

from app.connectors import ensure_builtin_connectors, get_registry


@pytest.fixture(autouse=True)
def _connectors():
    ensure_builtin_connectors()


@pytest.mark.asyncio
async def test_docusign_recipients_and_void(monkeypatch):
    from app.providers.docusign import DocuSignProviderClient

    client = DocuSignProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"signers": [{"email": "ada@example.com", "status": "sent"}]}
        return {"envelopeId": "env1", "status": "voided"}

    monkeypatch.setattr(client, "request_docusign", fake_request)
    creds = {"account_id": "acct", "access_token": "token"}

    recipients = await client.list_recipients(creds, "env1")
    assert recipients["signers"][0]["status"] == "sent"

    voided = await client.void_envelope(creds, "env1", "Duplicate envelope")
    assert voided["status"] == "voided"
    assert calls[-1][2]["json_body"]["voidedReason"] == "Duplicate envelope"


@pytest.mark.asyncio
async def test_sendgrid_templates_and_delete_contacts(monkeypatch):
    from app.providers.sendgrid import SendGridProviderClient

    client = SendGridProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"result": [{"id": "t1", "name": "Welcome"}]}
        return {"job_id": "job1"}

    monkeypatch.setattr(client, "request_sendgrid", fake_request)
    creds = {"api_key": "SG.token"}

    templates = await client.list_templates(creds)
    assert templates["result"][0]["name"] == "Welcome"

    deleted = await client.delete_contacts(creds, ["c1", "c2"])
    assert deleted["job_id"] == "job1"
    assert calls[-1][2]["params"]["ids"] == "c1,c2"


@pytest.mark.asyncio
async def test_zoho_delete_records_and_list_users(monkeypatch):
    from app.providers.zoho_crm import ZohoCrmProviderClient

    client = ZohoCrmProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "DELETE":
            return {"data": [{"code": "SUCCESS", "details": {"id": "1"}}]}
        return {"users": [{"id": "u1", "email": "ada@example.com"}]}

    monkeypatch.setattr(client, "request_zoho", fake_request)
    creds = {"access_token": "token"}

    deleted = await client.delete_records(creds, "Leads", ["1", "2"])
    assert deleted["data"][0]["code"] == "SUCCESS"
    assert calls[-1][2]["params"]["ids"] == "1,2"

    users = await client.list_users(creds)
    assert users["users"][0]["email"] == "ada@example.com"


@pytest.mark.asyncio
async def test_pagerduty_acknowledge_and_services(monkeypatch):
    from app.providers.pagerduty import PagerDutyProviderClient

    client = PagerDutyProviderClient()
    calls = []

    async def fake_request(creds, method, path, what, **kwargs):
        calls.append((method, path, kwargs))
        return {"incident": {"id": "i1", "status": "acknowledged"}}

    async def fake_get(creds, path, what, params=None, timeout=30.0):
        calls.append(("GET", path, params))
        return {"services": [{"id": "s1", "name": "API"}]}

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "_get", fake_get)
    creds = {"api_token": "token"}

    acked = await client.acknowledge_incident(creds, "i1")
    assert acked["incident"]["status"] == "acknowledged"
    assert calls[-1][2]["body"]["incident"]["status"] == "acknowledged"

    services = await client.list_services(creds, limit=10)
    assert services["services"][0]["name"] == "API"


@pytest.mark.asyncio
async def test_intercom_update_and_delete_contact(monkeypatch):
    from app.providers.intercom import IntercomProviderClient

    client = IntercomProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "PUT":
            return {"id": "c1", "name": "Ada"}
        return {"id": "c1", "deleted": True}

    monkeypatch.setattr(client, "request_intercom", fake_request)
    creds = {"access_token": "token"}

    updated = await client.update_contact(creds, "c1", {"name": "Ada"})
    assert updated["name"] == "Ada"
    assert calls[-1][2]["json_body"]["name"] == "Ada"

    deleted = await client.delete_contact(creds, "c1")
    assert deleted["deleted"] is True
    assert calls[-1][0] == "DELETE"


@pytest.mark.asyncio
async def test_box_delete_folder_and_copy_file(monkeypatch):
    from app.providers.box import BoxProviderClient

    client = BoxProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "DELETE":
            return {"deleted": True}
        return {"id": "f2", "name": "copy.txt"}

    monkeypatch.setattr(client, "request_box", fake_request)
    creds = {"access_token": "token"}

    deleted = await client.delete_folder(creds, "folder1", recursive=True)
    assert deleted["deleted"] is True
    assert calls[-1][2]["params"]["recursive"] == "true"

    copied = await client.copy_file(creds, "file1", parent_id="folder2", name="copy.txt")
    assert copied["name"] == "copy.txt"
    assert calls[-1][2]["json_body"]["parent"]["id"] == "folder2"


@pytest.mark.asyncio
async def test_depth_round8_connector_routes_map_new_operations(monkeypatch):
    from app.connectors.box_connector import BoxConnector
    from app.connectors.docusign_connector import DocuSignConnector
    from app.connectors.intercom_connector import IntercomConnector
    from app.connectors.pagerduty_connector import PagerDutyConnector
    from app.connectors.sendgrid_connector import SendGridConnector
    from app.connectors.zoho_crm_connector import ZohoCrmConnector

    docusign = DocuSignConnector()

    async def fake_void(creds, envelope_id, reason, **kwargs):
        assert (envelope_id, reason) == ("env1", "Duplicate")
        return {"status": "voided"}

    monkeypatch.setattr(docusign._provider, "void_envelope", fake_void)
    voided = await docusign.op_execute(
        "void_envelope", {"envelope_id": "env1", "void_reason": "Duplicate"},
        context={"credentials": {"docusign": {"account_id": "a", "access_token": "x"}}},
    )
    assert voided["status"] == "voided"

    sendgrid = SendGridConnector()

    async def fake_delete(creds, ids, **kwargs):
        assert ids == ["c1"]
        return {"job_id": "job1"}

    monkeypatch.setattr(sendgrid._provider, "delete_contacts", fake_delete)
    deleted = await sendgrid.op_execute(
        "delete_contacts", {"ids": ["c1"]},
        context={"credentials": {"sendgrid": {"api_key": "x"}}},
    )
    assert deleted["job_id"] == "job1"

    zoho = ZohoCrmConnector()

    async def fake_delete_records(creds, module, ids, **kwargs):
        assert (module, ids) == ("Leads", ["1"])
        return {"data": [{"code": "SUCCESS"}]}

    monkeypatch.setattr(zoho._provider, "delete_records", fake_delete_records)
    deleted = await zoho.op_execute(
        "delete_records", {"module": "Leads", "ids": ["1"]},
        context={"credentials": {"zoho_crm": {"access_token": "x"}}},
    )
    assert deleted["data"][0]["code"] == "SUCCESS"

    pagerduty = PagerDutyConnector()

    async def fake_ack(creds, incident_id, **kwargs):
        assert incident_id == "i1"
        return {"incident": {"status": "acknowledged"}}

    monkeypatch.setattr(pagerduty._provider, "acknowledge_incident", fake_ack)
    acked = await pagerduty.op_execute(
        "acknowledge_incident", {"incident_id": "i1"},
        context={"credentials": {"pagerduty": {"api_token": "x"}}},
    )
    assert acked["incident"]["status"] == "acknowledged"

    intercom = IntercomConnector()

    async def fake_update(creds, contact_id, fields, **kwargs):
        assert (contact_id, fields["name"]) == ("c1", "Ada")
        return {"id": contact_id, "name": fields["name"]}

    monkeypatch.setattr(intercom._provider, "update_contact", fake_update)
    updated = await intercom.op_execute(
        "update_contact", {"contact_id": "c1", "name": "Ada"},
        context={"credentials": {"intercom": {"access_token": "x"}}},
    )
    assert updated["name"] == "Ada"

    box = BoxConnector()

    async def fake_delete_folder(creds, folder_id, **kwargs):
        assert folder_id == "folder1"
        return {"deleted": True}

    monkeypatch.setattr(box._provider, "delete_folder", fake_delete_folder)
    deleted = await box.op_execute(
        "delete_folder", {"folder_id": "folder1", "recursive": True},
        context={"credentials": {"box": {"access_token": "x"}}},
    )
    assert deleted["deleted"] is True


def test_depth_round8_definitions_expose_new_operations():
    expected = {
        "docusign": {"list_recipients", "void_envelope"},
        "sendgrid": {"list_templates", "delete_contacts"},
        "zoho_crm": {"delete_records", "list_users"},
        "pagerduty": {"acknowledge_incident", "list_services"},
        "intercom": {"update_contact", "delete_contact"},
        "box": {"delete_folder", "copy_file"},
    }
    for key, operations in expected.items():
        definition = get_registry().get_definition(key)
        assert definition is not None
        assert operations <= set(definition.operations), (key, set(definition.operations))
