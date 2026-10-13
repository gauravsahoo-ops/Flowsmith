"""HubSpot connector: cursor pagination, list and delete operations.

Every assertion is backed by a request captured from the mock transport, so
these tests fail if the connector stops paging, stops sending the cursor, or
reports an outcome it did not observe.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.hubspot_connector import HubSpotConnector

BASE = "https://api.hubapi.com"
CREDS = {"private_token": "pat-na1-0000-0000-0000-000000000000"}
CTX = {"credentials": {"hubspot": CREDS}}


def _search_page(records, *, after=None, prev_after=None):
    body = {"results": records}
    if after:
        body["paging"] = {"next": {"after": after, "link": ""}}
    if prev_after:
        body.setdefault("paging", {})["prev"] = {"after": prev_after, "link": ""}
    return httpx.Response(200, json=body)


def _list_page(records, *, after=None):
    body = {"results": records}
    if after:
        body["paging"] = {"next": {"after": after, "link": ""}}
    return httpx.Response(200, json=body)


@pytest.fixture(autouse=True)
def connector():
    return HubSpotConnector()


@pytest.mark.asyncio
async def test_search_single_page_does_not_send_a_cursor(connector):
    with respx.mock:
        route = respx.post(f"{BASE}/crm/v3/objects/contacts/search").mock(
            return_value=_search_page([{"id": "1"}])
        )

        out = await connector.op_execute(
            "search",
            {"object_type": "contacts", "search_field": "email", "search_value": "a@b.c"},
            context=CTX,
        )

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        # First page carries no cursor and the connector's default page size.
        assert "offset" not in sent
        assert sent["limit"] == 100
        assert sent["filterGroups"][0]["filters"][0]["propertyName"] == "email"

        assert out["found"] is True
        assert out["records"] == [{"id": "1"}]
        assert out["pages_fetched"] == 1
        assert out["has_more"] is False
        assert out["next_offset"] is None


@pytest.mark.asyncio
async def test_search_stops_after_one_page_by_default(connector):
    """Without return_all, exactly one request is made even if more exist."""
    with respx.mock:
        route = respx.post(f"{BASE}/crm/v3/objects/contacts/search").mock(
            return_value=_search_page([{"id": "1"}], after="CURSOR-1")
        )

        out = await connector.op_execute(
            "search",
            {"object_type": "contacts", "search_field": "email", "search_value": "a@b.c"},
            context=CTX,
        )

        assert route.call_count == 1
        assert out["has_more"] is True
        assert out["next_offset"] == "CURSOR-1"
        assert out["pages_fetched"] == 1


@pytest.mark.asyncio
async def test_search_return_all_follows_the_cursor(connector):
    pages = [
        _search_page([{"id": "1"}], after="CURSOR-1"),
        _search_page([{"id": "2"}], after="CURSOR-2"),
        _search_page([{"id": "3"}]),
    ]

    with respx.mock:
        route = respx.post(f"{BASE}/crm/v3/objects/contacts/search").mock(
            side_effect=pages
        )

        out = await connector.op_execute(
            "search",
            {
                "object_type": "contacts",
                "search_field": "email",
                "search_value": "a@b.c",
                "return_all": True,
                "limit": 1,
            },
            context=CTX,
        )

        assert route.call_count == 3

        # Page 1: no cursor. Page 2/3: cursor from the previous response.
        bodies = [json.loads(c.request.content) for c in route.calls]
        assert "offset" not in bodies[0]
        assert bodies[1]["offset"] == {"after": "CURSOR-1"}
        assert bodies[2]["offset"] == {"after": "CURSOR-2"}
        assert all(b["limit"] == 1 for b in bodies)

        assert out["records"] == [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        assert out["total"] == 3
        assert out["pages_fetched"] == 3
        assert out["has_more"] is False
        assert out["next_offset"] is None


@pytest.mark.asyncio
async def test_search_return_all_respects_max_pages(connector):
    """max_pages is a hard stop so a runaway cursor cannot loop forever."""

    def endless(*_args, **_kwargs):
        # Each response advertises another page; the loop must still stop.
        return _search_page([{"id": "x"}], after="ALWAYS-MORE")

    with respx.mock:
        route = respx.post(f"{BASE}/crm/v3/objects/contacts/search").mock(side_effect=endless)

        out = await connector.op_execute(
            "search",
            {
                "object_type": "contacts",
                "search_field": "email",
                "search_value": "a@b.c",
                "return_all": True,
                "max_pages": 4,
            },
            context=CTX,
        )

        assert route.call_count == 4
        assert out["pages_fetched"] == 4
        assert out["has_more"] is True
        assert out["next_offset"] == "ALWAYS-MORE"


@pytest.mark.asyncio
async def test_search_accepts_an_explicit_starting_cursor(connector):
    with respx.mock:
        route = respx.post(f"{BASE}/crm/v3/objects/contacts/search").mock(
            return_value=_search_page([{"id": "9"}])
        )

        await connector.op_execute(
            "search",
            {
                "object_type": "contacts",
                "search_field": "email",
                "search_value": "a@b.c",
                "after": "START-HERE",
            },
            context=CTX,
        )

        body = json.loads(route.calls.last.request.content)
        assert body["offset"] == {"after": "START-HERE"}


@pytest.mark.asyncio
async def test_list_pages_with_the_v3_cursor_contract(connector):
    with respx.mock:
        route = respx.get(f"{BASE}/crm/v3/objects/companies").mock(
            side_effect=[
                _list_page([{"id": "a"}], after="P2"),
                _list_page([{"id": "b"}]),
            ]
        )

        out = await connector.op_execute(
            "list",
            {"object_type": "companies", "return_all": True, "limit": 1, "property_names": ["name"]},
            context=CTX,
        )

        assert route.call_count == 2
        first = dict(route.calls[0].request.url.params)
        second = dict(route.calls[1].request.url.params)

        assert first["limit"] == "1"
        assert first["properties"] == "name"
        assert "after" not in first
        assert second["limit"] == "1"
        assert second["after"] == "P2"

        assert out["records"] == [{"id": "a"}, {"id": "b"}]
        assert out["count"] == 2
        assert out["pages_fetched"] == 2
        assert out["has_more"] is False
        assert out["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_single_page_reports_the_next_cursor(connector):
    with respx.mock:
        route = respx.get(f"{BASE}/crm/v3/objects/deals").mock(
            return_value=_list_page([{"id": "d1"}], after="NEXT")
        )

        out = await connector.op_execute("list", {"object_type": "deals"}, context=CTX)

        assert route.call_count == 1
        assert out["has_more"] is True
        assert out["next_cursor"] == "NEXT"
        assert out["count"] == 1


@pytest.mark.asyncio
async def test_list_includes_archived_when_asked(connector):
    with respx.mock:
        route = respx.get(f"{BASE}/crm/v3/objects/contacts").mock(
            return_value=_list_page([])
        )

        await connector.op_execute(
            "list", {"object_type": "contacts", "include_archived": True}, context=CTX
        )

        assert route.calls.last.request.url.params.get("archived") == "true"


@pytest.mark.asyncio
async def test_delete_reports_the_observed_http_status(connector):
    with respx.mock:
        # 204 with an empty body is HubSpot's normal delete answer.
        route = respx.delete(f"{BASE}/crm/v3/objects/contacts/42").mock(
            return_value=httpx.Response(204)
        )

        out = await connector.op_execute(
            "delete", {"object_type": "contacts", "record_id": "42"}, context=CTX
        )

        assert route.called
        assert route.calls.last.request.headers["Authorization"].startswith("Bearer ")
        assert out["deleted"] is True
        assert out["http_status"] == 204
        assert out["id"] == "42"


@pytest.mark.asyncio
async def test_delete_body_can_carry_the_deleted_flag(connector):
    with respx.mock:
        respx.delete(f"{BASE}/crm/v3/objects/contacts/7").mock(
            return_value=httpx.Response(200, json={"deleted": True, "id": "7"})
        )

        out = await connector.op_execute(
            "delete", {"object_type": "contacts", "record_id": "7"}, context=CTX
        )
        assert out["deleted"] is True


@pytest.mark.asyncio
async def test_delete_failure_raises_instead_of_reporting_success(connector):
    with respx.mock:
        respx.delete(f"{BASE}/crm/v3/objects/contacts/404").mock(
            return_value=httpx.Response(404, json={"message": "not found"})
        )

        with pytest.raises(ConnectorError) as exc:
            await connector.op_execute(
                "delete", {"object_type": "contacts", "record_id": "404"}, context=CTX
            )
        assert exc.value.code == ConnectorErrorCode.NOT_FOUND.value


@pytest.mark.asyncio
async def test_list_rejects_an_unsupported_object_type_before_any_call(connector):
    with respx.mock:
        route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, json={}))

        with pytest.raises(ConnectorError) as exc:
            await connector.op_execute("list", {"object_type": "../../etc/passwd"}, context=CTX)

        assert exc.value.code == ConnectorErrorCode.BAD_REQUEST.value
        assert route.call_count == 0


@pytest.mark.asyncio
async def test_unknown_operation_is_rejected(connector):
    with pytest.raises(ConnectorError) as exc:
        await connector.op_execute("teleport", {"object_type": "contacts"}, context=CTX)
    assert exc.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_missing_credential_raises_before_any_request(connector):
    with respx.mock:
        route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(ConnectorError):
            await connector.op_execute(
                "list", {"object_type": "contacts"}, context={"credentials": {"hubspot": {}}}
            )
        assert route.call_count == 0
