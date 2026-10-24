"""Depth pass 4: Airtable, Asana, Trello, Dropbox, Zendesk, and Discord."""

from __future__ import annotations

import pytest

from app.connectors import ensure_builtin_connectors, get_registry
from tests.test_api._connector_fakes import json_response


@pytest.fixture(autouse=True)
def _connectors():
    ensure_builtin_connectors()


@pytest.mark.asyncio
async def test_airtable_list_bases_and_delete_record(monkeypatch):
    from app.providers.airtable import AirtableProviderClient

    client = AirtableProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/meta/bases":
            return json_response(200, {
                "bases": [{"id": "app1234567890", "name": "Ops", "permissionLevel": "create"}],
            })
        return json_response(200, {"deleted": True, "id": "rec1234567890"})

    monkeypatch.setattr(client, "request_airtable", fake_request)
    creds = {"personal_access_token": "token"}

    bases = await client.list_bases(creds)
    assert bases["bases"][0]["name"] == "Ops"
    assert bases["bases"][0]["permission_level"] == "create"

    deleted = await client.delete_record(
        creds, "app1234567890", "Tasks", "rec1234567890",
    )
    assert deleted["deleted"] is True
    assert calls[-1][0] == "DELETE"
    assert calls[-1][1].endswith("/rec1234567890")


@pytest.mark.asyncio
async def test_asana_list_projects_and_delete_task(monkeypatch):
    from app.providers.asana import AsanaProviderClient

    client = AsanaProviderClient()
    calls = []

    async def fake_request(method, path, creds, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/projects":
            return [{"gid": "p1", "name": "Launch"}]
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"access_token": "token"}

    projects = await client.list_projects(creds, workspace_id="w1")
    assert projects[0]["name"] == "Launch"
    assert calls[0][2]["params"] == {"workspace": "w1"}

    deleted = await client.delete_task(creds, "t1")
    assert deleted["deleted"] is True
    assert calls[-1][0] == "DELETE"


@pytest.mark.asyncio
async def test_trello_list_lists_and_update_card(monkeypatch):
    from app.providers.trello import TrelloProviderClient

    client = TrelloProviderClient()
    calls = []

    async def fake_request(method, path, creds, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/boards/b1/lists":
            return [{"id": "l1", "name": "Todo"}]
        return {"id": "c1", "name": "Updated"}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"api_key": "key", "api_token": "token"}

    lists = await client.list_lists(creds, "b1")
    assert lists[0]["name"] == "Todo"

    updated = await client.update_card(
        creds, "c1", {"name": "Updated", "idList": "l2", "closed": True},
    )
    assert updated["name"] == "Updated"
    assert calls[-1][0] == "PUT"
    assert calls[-1][2]["params"]["idList"] == "l2"
    assert calls[-1][2]["params"]["closed"] is True


@pytest.mark.asyncio
async def test_dropbox_search_and_move(monkeypatch):
    from app.providers.dropbox import DropboxProviderClient

    client = DropboxProviderClient()
    calls = []

    async def fake_rpc(creds, path, body, what, timeout=30.0):
        calls.append((path, body))
        if path == "/files/search_v2":
            return {"matches": [{"metadata": {"name": "a.txt"}}]}
        return {"metadata": {"path_display": "/archive/a.txt"}}

    monkeypatch.setattr(client, "_rpc", fake_rpc)
    creds = {"access_token": "token"}

    found = await client.search(creds, "a.txt", path="/docs", limit=10)
    assert found["matches"][0]["metadata"]["name"] == "a.txt"
    assert calls[0][1]["options"] == {"max_results": 10, "path": "/docs"}

    moved = await client.move(creds, "/docs/a.txt", "/archive/a.txt")
    assert moved["metadata"]["path_display"] == "/archive/a.txt"
    assert calls[-1][1]["from_path"] == "/docs/a.txt"


@pytest.mark.asyncio
async def test_zendesk_list_users_and_delete_ticket(monkeypatch):
    from app.providers.zendesk import ZendeskProviderClient

    client = ZendeskProviderClient()
    calls = []

    async def fake_request(creds, method, path, what, **kwargs):
        calls.append((method, path, what, kwargs))
        if path == "/users.json":
            return {"users": [{"id": 1, "name": "Ada"}]}
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"email": "ada@example.com", "api_token": "token", "subdomain": "acme"}

    users = await client.list_users(creds, role="agent")
    assert users["users"][0]["name"] == "Ada"
    assert calls[0][3]["params"] == {"per_page": 25, "role": "agent"}

    deleted = await client.delete_ticket(creds, "42")
    assert deleted["deleted"] is True
    assert calls[-1][0] == "DELETE"


@pytest.mark.asyncio
async def test_discord_list_channels_and_messages(monkeypatch):
    from app.providers.discord import DiscordProviderClient

    client = DiscordProviderClient()
    calls = []

    async def fake_request(**kwargs):
        calls.append(kwargs)
        if "/guilds/" in kwargs["url"]:
            return json_response(200, [
                {"id": "10", "name": "general", "type": 0, "position": 0, "parent_id": None},
            ])
        return json_response(200, [
            {"id": "m1", "content": "hello", "author": {"username": "ada"}, "timestamp": "2026-01-01T00:00:00Z"},
        ])

    monkeypatch.setattr(client, "authorized_request", fake_request)
    creds = {"bot_token": "token"}

    channels = await client.list_channels(creds, "99")
    assert channels["channels"][0]["name"] == "general"

    messages = await client.list_messages(creds, "10", limit=5)
    assert messages["messages"][0]["content"] == "hello"
    assert calls[-1]["params"] == {"limit": 5}


@pytest.mark.asyncio
async def test_depth_round4_connector_routes_map_new_operations(monkeypatch):
    from app.connectors.airtable_connector import AirtableConnector
    from app.connectors.asana_connector import AsanaConnector
    from app.connectors.discord_connector import DiscordConnector
    from app.connectors.dropbox_connector import DropboxConnector
    from app.connectors.trello_connector import TrelloConnector
    from app.connectors.zendesk_connector import ZendeskConnector

    airtable = AirtableConnector()

    async def fake_bases(creds, **kwargs):
        return {"bases": [{"id": "app1234567890"}], "count": 1}

    monkeypatch.setattr(airtable._provider, "list_bases", fake_bases)
    bases = await airtable.op_execute(
        "list_bases", {}, context={"credentials": {"airtable": {"personal_access_token": "x"}}},
    )
    assert bases["count"] == 1

    asana = AsanaConnector()

    async def fake_projects(creds, workspace_id, **kwargs):
        assert workspace_id == "w1"
        return [{"gid": "p1"}]

    monkeypatch.setattr(asana._provider, "list_projects", fake_projects)
    projects = await asana.op_execute(
        "list_projects", {"workspace_id": "w1"},
        context={"credentials": {"asana": {"access_token": "x"}}},
    )
    assert projects["projects"][0]["gid"] == "p1"

    trello = TrelloConnector()

    async def fake_update(creds, card_id, fields, **kwargs):
        assert card_id == "c1"
        assert fields["idList"] == "l2"
        return {"id": "c1", "name": "Updated"}

    monkeypatch.setattr(trello._provider, "update_card", fake_update)
    updated = await trello.op_execute(
        "update_card", {"card_id": "c1", "list_id": "l2"},
        context={"credentials": {"trello": {"api_key": "k", "api_token": "t"}}},
    )
    assert updated["name"] == "Updated"

    dropbox = DropboxConnector()

    async def fake_move(creds, from_path, to_path, **kwargs):
        assert (from_path, to_path) == ("/a.txt", "/b.txt")
        return {"metadata": {"path_display": "/b.txt"}}

    monkeypatch.setattr(dropbox._provider, "move", fake_move)
    moved = await dropbox.op_execute(
        "move", {"from_path": "/a.txt", "to_path": "/b.txt"},
        context={"credentials": {"dropbox": {"access_token": "x"}}},
    )
    assert moved["metadata"]["path_display"] == "/b.txt"

    zendesk = ZendeskConnector()

    async def fake_delete(creds, ticket_id, **kwargs):
        assert ticket_id == "42"
        return {"ticket_id": ticket_id, "deleted": True}

    monkeypatch.setattr(zendesk._provider, "delete_ticket", fake_delete)
    deleted = await zendesk.op_execute(
        "delete_ticket", {"ticket_id": "42"},
        context={"credentials": {"zendesk": {"api_token": "x"}}},
    )
    assert deleted["deleted"] is True

    discord = DiscordConnector()

    async def fake_messages(creds, channel_id, limit, **kwargs):
        assert (channel_id, limit) == ("10", 5)
        return {"messages": [{"id": "m1"}], "count": 1}

    monkeypatch.setattr(discord._provider, "list_messages", fake_messages)
    messages = await discord.op_execute(
        "list_messages", {"channel_id": "10", "limit": 5},
        context={"credentials": {"discord": {"bot_token": "x"}}},
    )
    assert messages["count"] == 1


def test_depth_round4_definitions_expose_new_operations():
    expected = {
        "airtable": {"delete_record", "list_bases"},
        "asana": {"list_projects", "delete_task"},
        "trello": {"list_lists", "update_card"},
        "dropbox": {"search", "move"},
        "zendesk": {"list_users", "delete_ticket"},
        "discord": {"list_channels", "list_messages"},
    }
    for key, operations in expected.items():
        definition = get_registry().get_definition(key)
        assert definition is not None
        assert operations <= set(definition.operations), (key, set(definition.operations))
