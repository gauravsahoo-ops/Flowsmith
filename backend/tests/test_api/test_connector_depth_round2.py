"""Depth pass 2: HubSpot, Dynamics, Google, Stripe, and Salesforce operations."""

from __future__ import annotations

import pytest

from app.connectors import get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


@pytest.mark.asyncio
async def test_hubspot_owner_and_pipelines(monkeypatch):
    from app.providers.hubspot import HubSpotProviderClient

    client = HubSpotProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path))
        if "owners" in path:
            return json_response(200, {
                "id": "42", "email": "owner@example.com",
                "firstName": "Ada", "lastName": "Lovelace",
                "userId": 42, "teams": [{"name": "RevOps"}],
            })
        return json_response(200, {"results": [{
            "id": "p1", "label": "Sales", "displayOrder": 0,
            "stages": [{"id": "s1", "label": "Qualified", "displayOrder": 0,
                        "metadata": {"probability": 0.2}}],
        }]})

    monkeypatch.setattr(client, "request", fake_request)
    owner = await client.get_owner({"private_token": "x"}, "42")
    pipelines = await client.list_pipelines({"private_token": "x"}, "deals")

    assert owner["email"] == "owner@example.com"
    assert owner["teams"] == ["RevOps"]
    assert pipelines["pipelines"][0]["stages"][0]["label"] == "Qualified"
    assert calls == [
        ("GET", "/crm/v3/owners/42"),
        ("GET", "/crm/v3/pipelines/deals"),
    ]


@pytest.mark.asyncio
async def test_dynamics_whoami_and_tables(monkeypatch):
    from app.providers.dynamics_crm import DynamicsCrmProviderClient

    client = DynamicsCrmProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path))
        if "WhoAmI" in path:
            return json_response(200, {
                "UserId": "u1", "BusinessUnitId": "b1", "OrganizationId": "o1",
            })
        return json_response(200, {"value": [{
            "LogicalName": "account", "DisplayName": {"UserLocalizedLabel": {"Label": "Account"}},
            "EntitySetName": "accounts",
        }]})

    monkeypatch.setattr(client, "request", fake_request)
    me = await client.who_am_i({"instance_url": "https://org.crm.dynamics.com"})
    tables = await client.list_tables({"instance_url": "https://org.crm.dynamics.com"})

    assert me["OrganizationId"] == "o1"
    assert tables["tables"][0]["entity_set"] == "accounts"
    assert "EntityDefinitions" in calls[1][1]


@pytest.mark.asyncio
async def test_google_sheets_create_and_drive_folder_delete(monkeypatch):
    from app.providers.google_drive import GoogleDriveProviderClient
    from app.providers.google_sheets import GoogleSheetsProviderClient

    sheets = GoogleSheetsProviderClient()
    drive = GoogleDriveProviderClient()

    async def fake_sheets_request(**kwargs):
        assert kwargs["url"].endswith("/spreadsheets")
        assert kwargs["json_body"]["properties"]["title"] == "Q4"
        return json_response(200, {
            "spreadsheetId": "s1", "spreadsheetUrl": "https://docs.google.com/s1",
            "properties": {"title": "Q4"},
        })

    async def fake_drive_request(**kwargs):
        if kwargs["method"] == "DELETE":
            return json_response(204, {})
        assert kwargs["json_body"]["mimeType"].endswith("folder")
        return json_response(200, {"id": "f1", "name": "Reports"})

    monkeypatch.setattr(sheets, "authorized_request", fake_sheets_request)
    monkeypatch.setattr(drive, "authorized_request", fake_drive_request)

    created = await sheets.create_spreadsheet({"refresh_token": "x"}, "Q4")
    folder = await drive.create_folder({"refresh_token": "x"}, "Reports")
    deleted = await drive.delete_file({"refresh_token": "x"}, "f2")

    assert created["spreadsheet_id"] == "s1"
    assert folder["folder_id"] == "f1"
    assert deleted["deleted"] is True


@pytest.mark.asyncio
async def test_google_calendar_lists_calendars(monkeypatch):
    from app.providers.google_calendar import GoogleCalendarProviderClient

    client = GoogleCalendarProviderClient()

    async def fake_request(creds, method, path, **kwargs):
        assert path == "/calendar/v3/users/me/calendarList"
        return json_response(200, {"items": [{
            "id": "primary", "summary": "Main", "primary": True,
            "accessRole": "owner", "timeZone": "UTC",
        }]})

    monkeypatch.setattr(client, "request", fake_request)
    out = await client.list_calendars({"refresh_token": "x"})
    assert out["calendars"][0]["summary"] == "Main"
    assert out["count"] == 1


@pytest.mark.asyncio
async def test_stripe_customer_update_and_intent_list(monkeypatch):
    from app.providers.stripe import StripeProviderClient

    client = StripeProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "POST":
            return json_response(200, {"id": "cus_1", "email": "new@example.com", "name": "New"})
        return json_response(200, {"data": [{
            "id": "pi_1", "amount": 500, "currency": "usd",
            "status": "succeeded", "customer": "cus_1", "created": 1,
        }], "has_more": False})

    monkeypatch.setattr(client, "request_stripe", fake_request)
    updated = await client.update_customer({"secret_key": "sk_test"}, "cus_1", email="new@example.com")
    intents = await client.list_payment_intents({"secret_key": "sk_test"}, customer_id="cus_1")

    assert updated["email"] == "new@example.com"
    assert intents["payment_intents"][0]["id"] == "pi_1"
    assert calls[0][1] == "/customers/cus_1"
    assert calls[1][1] == "/payment_intents"
    assert calls[1][2]["query"]["customer"] == "cus_1"


@pytest.mark.asyncio
async def test_salesforce_org_limits(monkeypatch):
    from app.providers.salesforce import SalesforceProviderClient

    client = SalesforceProviderClient()

    async def fake_request(creds, method, path, **kwargs):
        assert path == "/limits"
        return json_response(200, {"DailyApiRequests": {"Max": 1000, "Remaining": 900}})

    monkeypatch.setattr(client, "request", fake_request)
    out = await client.org_limits({"access_token": "x", "instance_url": "https://org.my.salesforce.com"})
    assert out["limits"]["DailyApiRequests"]["Remaining"] == 900


def test_round2_definitions_expose_new_operations():
    expected = {
        "hubspot": {"get_owner", "list_pipelines"},
        "dynamics_crm": {"whoami", "list_tables"},
        "google_sheets": {"create_spreadsheet"},
        "google_drive": {"delete_file", "create_folder"},
        "google_calendar": {"list_calendars"},
        "stripe": {"update_customer", "list_payment_intents"},
        "salesforce": {"org_limits"},
    }
    for key, operations in expected.items():
        definition = get_registry().get_definition(key)
        assert definition is not None
        assert operations <= set(definition.operations), (key, set(definition.operations))
