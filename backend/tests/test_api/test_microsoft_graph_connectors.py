"""Microsoft Teams + Outlook connector tests (Phase 11 business connectors).

Shared microsoft_graph credential (client-credentials app). Proves:
token mint against the tenant's v2.0 endpoint, Teams channel message,
Outlook sendMail payload, 401 re-mint once then AUTH_FAILED.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = "app.providers.microsoft_graph"
CREDS = {"tenant_id": "11111111-2222-3333-4444-555555555555", "client_id": "app-id", "client_secret": "graph-secret"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_send_channel_message_mints_token_first():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"access_token": "MSAT_1", "expires_in": 3600}),
        json_response(200, {"id": "msg-1"}),
    ])
    try:
        from app.providers.microsoft_graph import MicrosoftGraphProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            MicrosoftGraphProviderClient().send_channel_message(
                CREDS, "team-1", "chan-1", "hello <team>", subject="Build done",
            )
        )
    finally:
        patcher.stop()

    assert out["message_id"] == "msg-1"
    # Client-credentials grant against the tenant-specific token endpoint.
    method0, url0, kwargs0 = fake.calls[0]
    assert url0 == f"https://login.microsoftonline.com/{CREDS['tenant_id']}/oauth2/v2.0/token"
    assert "grant_type=client_credentials" in kwargs0["data"]
    assert "scope=https%3A%2F%2Fgraph.microsoft.com%2F.default" in kwargs0["data"] or \
        "scope=https://graph.microsoft.com/.default" in kwargs0["data"]
    # The channel message carries escaped HTML + subject.
    method1, url1, kwargs1 = fake.calls[1]
    assert "/teams/team-1/channels/chan-1/messages" in url1
    body = kwargs1["json"]
    assert body["subject"] == "Build done"
    assert "&lt;team&gt;" in body["body"]["content"]


def test_outlook_send_mail_payload():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"access_token": "MSAT_2", "expires_in": 3600}),
        json_response(202, {}),
    ])
    try:
        from app.providers.microsoft_graph import MicrosoftGraphProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            MicrosoftGraphProviderClient().send_mail(
                CREDS, ["a@b.com", "c@d.com"], "Invoice", "See attached",
                cc=["boss@b.com"],
            )
        )
    finally:
        patcher.stop()

    assert out["sent"] is True
    _, url, kwargs = fake.calls[1]
    assert url.endswith("/me/sendMail")
    message = kwargs["json"]["message"]
    assert [r["emailAddress"]["address"] for r in message["toRecipients"]] == ["a@b.com", "c@d.com"]
    assert [r["emailAddress"]["address"] for r in message["ccRecipients"]] == ["boss@b.com"]
    assert kwargs["json"]["saveToSentItems"] is True


def test_outlook_message_folders_and_read_state():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"access_token": "MSAT_3", "expires_in": 3600}),
        json_response(200, {
            "id": "m1", "subject": "Hello", "isRead": False,
            "from": {"emailAddress": {"address": "a@b.com"}},
            "toRecipients": [{"emailAddress": {"address": "c@d.com"}}],
            "body": {"content": "body"},
        }),
        json_response(200, {"value": [{"id": "f1", "displayName": "Inbox", "totalItemCount": 4}]}),
        json_response(200, {"id": "m1", "isRead": True}),
    ])
    try:
        from app.providers.microsoft_graph import MicrosoftGraphProviderClient

        client = MicrosoftGraphProviderClient()
        message = asyncio.new_event_loop().run_until_complete(
            client.get_message(CREDS, "m1")
        )
        folders = asyncio.new_event_loop().run_until_complete(
            client.list_folders(CREDS)
        )
        marked = asyncio.new_event_loop().run_until_complete(
            client.mark_read(CREDS, "m1", True)
        )
    finally:
        patcher.stop()

    assert message["subject"] == "Hello"
    assert message["to"] == ["c@d.com"]
    assert folders["folders"][0]["display_name"] == "Inbox"
    assert marked["is_read"] is True
    assert fake.calls[1][1].endswith("/me/messages/m1")
    assert fake.calls[2][1].endswith("/me/mailFolders")


def test_outlook_move_and_delete_message():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"access_token": "MSAT_4", "expires_in": 3600}),
        json_response(200, {"id": "m2", "parentFolderId": "archive"}),
        json_response(204, {}),
    ])
    try:
        from app.providers.microsoft_graph import MicrosoftGraphProviderClient

        client = MicrosoftGraphProviderClient()
        moved = asyncio.new_event_loop().run_until_complete(
            client.move_message(CREDS, "m2", "archive")
        )
        deleted = asyncio.new_event_loop().run_until_complete(
            client.delete_message(CREDS, "m2")
        )
    finally:
        patcher.stop()

    assert moved["moved"] is True and moved["parent_folder_id"] == "archive"
    assert deleted["deleted"] is True
    assert fake.calls[1][1].endswith("/me/messages/m2/move")
    assert fake.calls[2][0] == "DELETE"


def test_teams_messages_members_and_create_channel():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"access_token": "MSAT_5", "expires_in": 3600}),
        json_response(200, {"value": [{"id": "m1", "subject": "Deploy", "body": {"content": "done"}}]}),
        json_response(200, {"value": [{"id": "u1", "displayName": "Ada", "email": "ada@example.com"}]}),
        json_response(201, {"id": "chan-new", "displayName": "ops"}),
    ])
    try:
        from app.providers.microsoft_graph import MicrosoftGraphProviderClient

        client = MicrosoftGraphProviderClient()
        messages = asyncio.new_event_loop().run_until_complete(
            client.list_channel_messages(CREDS, "t1", "c1")
        )
        members = asyncio.new_event_loop().run_until_complete(
            client.list_team_members(CREDS, "t1")
        )
        channel = asyncio.new_event_loop().run_until_complete(
            client.create_channel(CREDS, "t1", "ops")
        )
    finally:
        patcher.stop()

    assert messages["messages"][0]["subject"] == "Deploy"
    assert members["members"][0]["display_name"] == "Ada"
    assert channel["channel_id"] == "chan-new"
    assert fake.calls[1][1].endswith("/teams/t1/channels/c1/messages")
    assert fake.calls[2][1].endswith("/teams/t1/members")
    assert fake.calls[3][1].endswith("/teams/t1/channels")


def test_graph_connector_definitions_expose_deep_operations():
    outlook = get_registry().get_definition("outlook")
    teams = get_registry().get_definition("msteams")
    assert outlook is not None and teams is not None
    assert {
        "send", "list_messages", "get_message", "list_folders",
        "mark_read", "move_message", "delete_message",
    } <= set(outlook.operations)
    assert {
        "send_message", "list_teams", "list_channels", "list_channel_messages",
        "reply_to_message", "list_members", "create_channel",
    } <= set(teams.operations)


def test_missing_app_creds_is_not_configured():
    from app.providers.microsoft_graph import MicrosoftGraphProviderClient

    async def go():
        await MicrosoftGraphProviderClient().list_teams({"client_id": "only"})

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("partial creds should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)
    finally:
        loop.close()


def test_bad_client_secret_maps_to_auth_failed_after_single_remint():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"access_token": "STALE", "expires_in": 3600}),   # first mint
        json_response(401, {"error": {"message": "InvalidAuthenticationToken"}}),
        json_response(200, {"access_token": "FRESH", "expires_in": 3600}),   # re-mint on 401
        json_response(401, {"error": {"message": "InvalidAuthenticationToken"}}),  # still 401
    ])
    try:
        from app.providers.microsoft_graph import MicrosoftGraphProviderClient

        async def go():
            await MicrosoftGraphProviderClient().list_teams(CREDS)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("persistent 401 should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.AUTH_FAILED, ConnectorErrorCode.AUTH_FAILED.value)
            assert exc.retryable is False
        finally:
            loop.close()
        # Exactly one re-mint: the one-shot 401 refresh contract.
        mints = [c for c in fake.calls if "oauth2" in c[1]]
        assert len(mints) == 2
    finally:
        patcher.stop()


def test_connector_layer_routes_teams_and_outlook(monkeypatch):
    from app.connectors.msteams_connector import MSTeamsConnector
    from app.connectors.outlook_connector import OutlookConnector

    teams = MSTeamsConnector()

    async def fake_msg(creds, team_id, channel_id, content, subject="", timeout=30.0):
        assert creds == CREDS
        return {"message_id": "m1", "success": True}

    monkeypatch.setattr(teams._provider, "send_channel_message", fake_msg)

    out = asyncio.new_event_loop().run_until_complete(
        teams.op_execute(
            "execute",
            {"operation": "send_message", "team_id": "t", "channel_id": "c", "content": "hi"},
            {"credentials": {"microsoft_graph": CREDS}},
        )
    )
    assert out["success"] is True

    outlook = OutlookConnector()

    async def fake_send_mail(creds, to, subject, body, cc=None, save_to_sent=True, timeout=30.0):
        return {"sent": True}

    monkeypatch.setattr(outlook._provider, "send_mail", fake_send_mail)
    out2 = asyncio.new_event_loop().run_until_complete(
        outlook.op_execute(
            "", {"operation": "send", "to": ["x@y.z"], "subject": "s", "body": "b"},
            {"credentials": {"microsoft_graph": CREDS}},
        )
    )
    assert out2["sent"] is True
