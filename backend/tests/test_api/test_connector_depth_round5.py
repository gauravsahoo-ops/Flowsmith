"""Depth pass 5: Shopify, Monday, Pipedrive, Mailchimp, Google Docs, Zoom, Calendly."""

from __future__ import annotations

import hashlib
import json

import pytest

from app.connectors import ensure_builtin_connectors, get_registry
from tests.test_api._connector_fakes import json_response


@pytest.fixture(autouse=True)
def _connectors():
    ensure_builtin_connectors()


@pytest.mark.asyncio
async def test_shopify_list_orders_and_update_product(monkeypatch):
    from app.providers.shopify import ShopifyProviderClient

    client = ShopifyProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/orders.json":
            return json_response(200, {"orders": [{
                "id": 1, "name": "#1001", "email": "buyer@example.com",
                "total_price": "42.00", "financial_status": "paid",
                "fulfillment_status": "fulfilled", "created_at": "2026-01-01",
            }]})
        return json_response(200, {"product": {"id": 9, "title": "Updated", "variants": []}})

    monkeypatch.setattr(client, "request_shopify", fake_request)
    creds = {"shop_domain": "acme.myshopify.com", "access_token": "token"}

    orders = await client.list_orders(creds, limit=10)
    assert orders["orders"][0]["name"] == "#1001"
    assert orders["count"] == 1

    updated = await client.update_product(creds, "9", {"title": "Updated", "status": "draft"})
    assert updated["title"] == "Updated"
    assert calls[-1][0] == "PUT"
    assert calls[-1][2]["json_body"]["product"]["status"] == "draft"


@pytest.mark.asyncio
async def test_monday_update_and_delete_item(monkeypatch):
    from app.providers.monday import MondayProviderClient

    client = MondayProviderClient()
    calls = []

    async def fake_gql(creds, query, variables, what, timeout=30.0):
        calls.append((query, variables))
        if "change_multiple_column_values" in query:
            return {"change_multiple_column_values": {"id": "i1", "name": "Updated"}}
        return {"delete_item": {"id": "i1"}}

    monkeypatch.setattr(client, "_gql", fake_gql)
    creds = {"api_token": "token"}

    updated = await client.update_item(creds, "b1", "i1", {"status": {"label": "Done"}})
    assert updated["item"]["name"] == "Updated"
    assert json.loads(calls[0][1]["values"]) == {"status": {"label": "Done"}}

    deleted = await client.delete_item(creds, "i1")
    assert deleted["deleted"] is True
    assert deleted["item"]["id"] == "i1"


@pytest.mark.asyncio
async def test_pipedrive_list_persons_and_delete_deal(monkeypatch):
    from app.providers.pipedrive import PipedriveProviderClient

    client = PipedriveProviderClient()
    calls = []

    async def fake_request(creds, method, path, what, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/persons":
            return {"data": [{"id": 7, "name": "Ada"}], "success": True}
        return {"data": {"id": 42}, "success": True}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"api_token": "token", "domain": "acme.pipedrive.com"}

    people = await client.list_persons(creds, limit=10)
    assert people["data"][0]["name"] == "Ada"

    deleted = await client.delete_deal(creds, "42")
    assert deleted["deleted"] is True
    assert calls[-1][0] == "DELETE"


@pytest.mark.asyncio
async def test_mailchimp_list_and_delete_member(monkeypatch):
    from app.providers.mailchimp import MailchimpProviderClient

    client = MailchimpProviderClient()
    calls = []

    async def fake_request(creds, method, path, what, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"members": [{"email_address": "ada@example.com", "status": "subscribed"}]}
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"api_key": "key-us21"}

    members = await client.list_members(creds, "list1", status="subscribed")
    assert members["members"][0]["email_address"] == "ada@example.com"

    deleted = await client.delete_member(creds, "list1", "ada@example.com")
    assert deleted["deleted"] is True
    expected_hash = hashlib.md5(b"ada@example.com").hexdigest()
    assert calls[-1][0] == "DELETE"
    assert calls[-1][1].endswith(expected_hash)


@pytest.mark.asyncio
async def test_google_docs_text_and_replace(monkeypatch):
    from app.providers.google_docs import GoogleDocsProviderClient

    client = GoogleDocsProviderClient()
    calls = []

    async def fake_request(creds, method, path, what, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {
                "documentId": "doc1",
                "title": "Plan",
                "body": {"content": [
                    {"paragraph": {"elements": [
                        {"textRun": {"content": "Hello "}},
                        {"textRun": {"content": "world"}},
                    ]}},
                ]},
            }
        return {"replies": [{"replaceAllText": {"occurrencesChanged": 2}}]}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"access_token": "token"}

    text = await client.get_document_text(creds, "doc1")
    assert text["text"] == "Hello world"
    assert text["length"] == 11

    replaced = await client.replace_text(
        creds, "doc1", "world", replacement="there", match_case=True,
    )
    assert replaced["replies"][0]["replaceAllText"]["occurrencesChanged"] == 2
    request_body = calls[-1][2]["body"]["requests"][0]["replaceAllText"]
    assert request_body["containsText"] == {"text": "world", "matchCase": True}
    assert request_body["replaceText"] == "there"


@pytest.mark.asyncio
async def test_zoom_list_users_and_update_meeting(monkeypatch):
    from app.providers.zoom import ZoomProviderClient

    client = ZoomProviderClient()
    calls = []

    async def fake_request(method, path, creds, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/users":
            return {"users": [{"id": "u1", "email": "ada@example.com"}]}
        return {"id": 5, "topic": "Updated"}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"access_token": "token"}

    users = await client.list_users(creds, limit=10)
    assert users[0]["email"] == "ada@example.com"

    updated = await client.update_meeting(creds, "5", {"topic": "Updated", "duration": 45})
    assert updated["topic"] == "Updated"
    assert calls[-1][0] == "PATCH"
    assert calls[-1][2]["json_body"]["duration"] == 45


@pytest.mark.asyncio
async def test_calendly_invitees_and_scheduling_link(monkeypatch):
    from app.providers.calendly import CalendlyProviderClient

    client = CalendlyProviderClient()
    calls = []

    async def fake_get(creds, path, params, what, timeout=30.0):
        calls.append(("GET", path, params))
        return {"collection": [{"email": "ada@example.com", "status": "active"}]}

    async def fake_post(creds, path, what, body=None, timeout=30.0):
        calls.append(("POST", path, body))
        return {"resource": {"booking_url": "https://calendly.com/ada/30min"}}

    monkeypatch.setattr(client, "_get", fake_get)
    monkeypatch.setattr(client, "_post", fake_post)
    creds = {"access_token": "token"}

    invitees = await client.list_invitees(creds, "evt-1", count=10)
    assert invitees[0]["email"] == "ada@example.com"

    link = await client.create_scheduling_link(creds, "https://api.calendly.com/event_types/et1")
    assert link["scheduling_link"]["booking_url"].endswith("/30min")
    assert calls[-1][2]["owner_type"] == "EventType"


@pytest.mark.asyncio
async def test_depth_round5_connector_routes_map_new_operations(monkeypatch):
    from app.connectors.calendly_connector import CalendlyConnector
    from app.connectors.google_docs_connector import GoogleDocsConnector
    from app.connectors.mailchimp_connector import MailchimpConnector
    from app.connectors.monday_connector import MondayConnector
    from app.connectors.pipedrive_connector import PipedriveConnector
    from app.connectors.shopify_connector import ShopifyConnector
    from app.connectors.zoom_connector import ZoomConnector

    shopify = ShopifyConnector()

    async def fake_orders(creds, **kwargs):
        return {"orders": [{"id": 1}], "count": 1}

    monkeypatch.setattr(shopify._provider, "list_orders", fake_orders)
    orders = await shopify.op_execute(
        "list_orders", {"limit": 5},
        context={"credentials": {"shopify": {"shop_domain": "acme.myshopify.com", "access_token": "x"}}},
    )
    assert orders["count"] == 1

    monday = MondayConnector()

    async def fake_update(creds, board_id, item_id, columns, **kwargs):
        assert (board_id, item_id, columns) == ("b1", "i1", {"status": {"label": "Done"}})
        return {"item": {"id": "i1"}}

    monkeypatch.setattr(monday._provider, "update_item", fake_update)
    updated = await monday.op_execute(
        "update_item", {"board_id": "b1", "item_id": "i1", "column_values": {"status": {"label": "Done"}}},
        context={"credentials": {"monday": {"api_token": "x"}}},
    )
    assert updated["item"]["id"] == "i1"

    pipedrive = PipedriveConnector()

    async def fake_delete_deal(creds, deal_id, **kwargs):
        assert deal_id == "42"
        return {"deal_id": deal_id, "deleted": True}

    monkeypatch.setattr(pipedrive._provider, "delete_deal", fake_delete_deal)
    deleted = await pipedrive.op_execute(
        "delete_deal", {"deal_id": "42"},
        context={"credentials": {"pipedrive": {"api_token": "x", "domain": "acme.pipedrive.com"}}},
    )
    assert deleted["deleted"] is True

    mailchimp = MailchimpConnector()

    async def fake_delete_member(creds, list_id, email, **kwargs):
        assert (list_id, email) == ("list1", "ada@example.com")
        return {"deleted": True}

    monkeypatch.setattr(mailchimp._provider, "delete_member", fake_delete_member)
    removed = await mailchimp.op_execute(
        "delete_member", {"list_id": "list1", "email": "ada@example.com"},
        context={"credentials": {"mailchimp": {"api_key": "key-us21"}}},
    )
    assert removed["deleted"] is True

    docs = GoogleDocsConnector()

    async def fake_replace(creds, document_id, text, **kwargs):
        assert (document_id, text) == ("doc1", "hello")
        return {"replies": []}

    monkeypatch.setattr(docs._provider, "replace_text", fake_replace)
    replaced = await docs.op_execute(
        "replace_text", {"document_id": "doc1", "text": "hello", "replacement": "hi"},
        context={"credentials": {"google_docs": {"access_token": "x"}}},
    )
    assert replaced["replies"] == []

    zoom = ZoomConnector()

    async def fake_update_meeting(creds, meeting_id, fields, **kwargs):
        assert (meeting_id, fields["topic"]) == ("5", "Updated")
        return {"id": 5, "topic": "Updated"}

    monkeypatch.setattr(zoom._provider, "update_meeting", fake_update_meeting)
    meeting = await zoom.op_execute(
        "update_meeting", {"meeting_id": "5", "topic": "Updated"},
        context={"credentials": {"zoom": {"access_token": "x"}}},
    )
    assert meeting["topic"] == "Updated"

    calendly = CalendlyConnector()

    async def fake_link(creds, owner_uri, max_event_count, **kwargs):
        assert owner_uri.endswith("/et1")
        return {"scheduling_link": {"booking_url": "https://calendly.com/x"}, "success": True}

    monkeypatch.setattr(calendly._provider, "create_scheduling_link", fake_link)
    link = await calendly.op_execute(
        "create_scheduling_link", {"owner_uri": "https://api.calendly.com/event_types/et1"},
        context={"credentials": {"calendly": {"access_token": "x"}}},
    )
    assert link["success"] is True


def test_depth_round5_definitions_expose_new_operations():
    expected = {
        "shopify": {"list_orders", "update_product"},
        "monday": {"update_item", "delete_item"},
        "pipedrive": {"list_persons", "delete_deal"},
        "mailchimp": {"list_members", "delete_member"},
        "google_docs": {"get_document_text", "replace_text"},
        "zoom": {"list_users", "update_meeting"},
        "calendly": {"list_invitees", "create_scheduling_link"},
    }
    for key, operations in expected.items():
        definition = get_registry().get_definition(key)
        assert definition is not None
        assert operations <= set(definition.operations), (key, set(definition.operations))
