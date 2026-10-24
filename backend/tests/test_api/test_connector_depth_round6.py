"""Depth pass 6: QuickBooks, Xero, ServiceNow, Freshdesk, and Freshsales."""

from __future__ import annotations

import pytest

from app.connectors import ensure_builtin_connectors, get_registry


@pytest.fixture(autouse=True)
def _connectors():
    ensure_builtin_connectors()


@pytest.mark.asyncio
async def test_quickbooks_list_customers_and_invoices(monkeypatch):
    from app.providers.quickbooks import QuickBooksProviderClient

    client = QuickBooksProviderClient()
    calls = []

    async def fake_request(creds, method, path, what, **kwargs):
        calls.append((method, path, kwargs))
        if "Customer" in str(kwargs.get("body")):
            return {"QueryResponse": {"Customer": [{"Id": "1", "DisplayName": "Ada"}]}}
        return {"QueryResponse": {"Invoice": [{"Id": "2", "TotalAmt": 42}]}}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"access_token": "token", "realm_id": "realm"}

    customers = await client.list_customers(creds, limit=10)
    assert customers["QueryResponse"]["Customer"][0]["DisplayName"] == "Ada"
    assert "maxresults 10" in calls[0][2]["body"]

    invoices = await client.list_invoices(creds, limit=5)
    assert invoices["QueryResponse"]["Invoice"][0]["Id"] == "2"
    assert "maxresults 5" in calls[1][2]["body"]


@pytest.mark.asyncio
async def test_xero_get_and_create_contact(monkeypatch):
    from app.providers.xero import XeroProviderClient

    client = XeroProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"Contacts": [{"ContactID": "c1", "Name": "Ada"}]}
        return {"Contacts": [{"ContactID": "c2", "Name": "Grace"}]}

    monkeypatch.setattr(client, "request_xero", fake_request)
    creds = {"tenant_id": "tenant", "access_token": "token"}

    contact = await client.get_contact(creds, "c1")
    assert contact["Contacts"][0]["Name"] == "Ada"

    created = await client.create_contact(creds, "Grace", email="grace@example.com")
    assert created["Contacts"][0]["ContactID"] == "c2"
    assert calls[-1][2]["json_body"]["Contacts"][0]["EmailAddress"] == "grace@example.com"


@pytest.mark.asyncio
async def test_servicenow_list_users_and_add_comment(monkeypatch):
    from app.providers.servicenow import ServiceNowProviderClient

    client = ServiceNowProviderClient()
    calls = []

    async def fake_get(creds, table, suffix, what, params=None, timeout=30.0):
        calls.append(("GET", table, suffix, params))
        return {"result": [{"sys_id": "u1", "user_name": "ada"}]}

    async def fake_update(creds, table, sys_id, fields, timeout=30.0):
        calls.append(("PATCH", table, sys_id, fields))
        return {"result": {"sys_id": sys_id, **fields}}

    monkeypatch.setattr(client, "_get", fake_get)
    monkeypatch.setattr(client, "update_record", fake_update)
    creds = {"instance": "acme", "username": "u", "password": "p"}

    users = await client.list_users(creds, limit=10)
    assert users["result"][0]["user_name"] == "ada"

    commented = await client.add_comment(creds, "incident", "sys1", "Working on it", work_note=True)
    assert commented["result"]["work_notes"] == "Working on it"
    assert calls[-1][0] == "PATCH"


@pytest.mark.asyncio
async def test_freshdesk_list_contacts_and_delete_ticket(monkeypatch):
    from app.providers.freshdesk import FreshdeskProviderClient

    client = FreshdeskProviderClient()
    calls = []

    async def fake_request(creds, method, path, what, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return [{"id": 7, "name": "Ada"}]
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"email": "ada@example.com", "api_token": "token", "domain": "acme"}

    contacts = await client.list_contacts(creds, limit=10)
    assert contacts["contacts"][0]["name"] == "Ada"

    deleted = await client.delete_ticket(creds, "42")
    assert deleted["deleted"] is True
    assert calls[-1][0] == "DELETE"


@pytest.mark.asyncio
async def test_freshsales_update_and_delete_contact(monkeypatch):
    from app.providers.freshsales import FreshsalesProviderClient

    client = FreshsalesProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "PUT":
            return {"contact": {"id": "c1", "job_title": "CTO"}}
        return {}

    monkeypatch.setattr(client, "request_freshsales", fake_request)
    creds = {"domain": "acme", "api_key": "token"}

    updated = await client.update_contact(creds, "c1", {"job_title": "CTO"})
    assert updated["contact"]["job_title"] == "CTO"
    assert calls[-1][2]["json_body"]["contact"]["job_title"] == "CTO"

    deleted = await client.delete_contact(creds, "c1")
    assert deleted["deleted"] is True
    assert calls[-1][0] == "DELETE"


@pytest.mark.asyncio
async def test_depth_round6_connector_routes_map_new_operations(monkeypatch):
    from app.connectors.freshdesk_connector import FreshdeskConnector
    from app.connectors.freshsales_connector import FreshsalesConnector
    from app.connectors.quickbooks_connector import QuickBooksConnector
    from app.connectors.servicenow_connector import ServiceNowConnector
    from app.connectors.xero_connector import XeroConnector

    quickbooks = QuickBooksConnector()

    async def fake_customers(creds, limit, **kwargs):
        assert limit == 10
        return {"QueryResponse": {"Customer": []}}

    monkeypatch.setattr(quickbooks._provider, "list_customers", fake_customers)
    customers = await quickbooks.op_execute(
        "list_customers", {"limit": 10},
        context={"credentials": {"quickbooks": {"access_token": "x", "realm_id": "r"}}},
    )
    assert customers["QueryResponse"]["Customer"] == []

    xero = XeroConnector()

    async def fake_contact(creds, name, **kwargs):
        assert (name, kwargs["email"]) == ("Grace", "grace@example.com")
        return {"Contacts": [{"Name": name}]}

    monkeypatch.setattr(xero._provider, "create_contact", fake_contact)
    contact = await xero.op_execute(
        "create_contact", {"contact_name": "Grace", "contact_email": "grace@example.com"},
        context={"credentials": {"xero": {"tenant_id": "t", "access_token": "x"}}},
    )
    assert contact["Contacts"][0]["Name"] == "Grace"

    servicenow = ServiceNowConnector()

    async def fake_comment(creds, table, sys_id, comment, **kwargs):
        assert (table, sys_id, comment) == ("incident", "sys1", "Working")
        assert kwargs["work_note"] is True
        return {"result": {"sys_id": sys_id}}

    monkeypatch.setattr(servicenow._provider, "add_comment", fake_comment)
    comment = await servicenow.op_execute(
        "add_comment", {"table": "incident", "sys_id": "sys1", "comment": "Working", "work_note": True},
        context={"credentials": {"servicenow": {"instance": "acme"}}},
    )
    assert comment["result"]["sys_id"] == "sys1"

    freshdesk = FreshdeskConnector()

    async def fake_delete(creds, ticket_id, **kwargs):
        assert ticket_id == "42"
        return {"ticket_id": ticket_id, "deleted": True}

    monkeypatch.setattr(freshdesk._provider, "delete_ticket", fake_delete)
    deleted = await freshdesk.op_execute(
        "delete_ticket", {"ticket_id": "42"},
        context={"credentials": {"freshdesk": {"api_token": "x"}}},
    )
    assert deleted["deleted"] is True

    freshsales = FreshsalesConnector()

    async def fake_update(creds, contact_id, fields, **kwargs):
        assert (contact_id, fields["job_title"]) == ("c1", "CTO")
        return {"contact": {"id": contact_id, "job_title": fields["job_title"]}}

    monkeypatch.setattr(freshsales._provider, "update_contact", fake_update)
    updated = await freshsales.op_execute(
        "update_contact", {"contact_id": "c1", "job_title": "CTO"},
        context={"credentials": {"freshsales": {"domain": "acme", "api_key": "x"}}},
    )
    assert updated["contact"]["job_title"] == "CTO"


def test_depth_round6_definitions_expose_new_operations():
    expected = {
        "quickbooks": {"list_customers", "list_invoices"},
        "xero": {"get_contact", "create_contact"},
        "servicenow": {"list_users", "add_comment"},
        "freshdesk": {"list_contacts", "delete_ticket"},
        "freshsales": {"update_contact", "delete_contact"},
    }
    for key, operations in expected.items():
        definition = get_registry().get_definition(key)
        assert definition is not None
        assert operations <= set(definition.operations), (key, set(definition.operations))
