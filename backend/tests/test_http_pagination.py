"""Universal HTTP connector: cursor pagination and short-page termination.

The connector declares three pagination modes in its parameter union. `cursor`
was previously accepted by the type checker and then silently ignored — every
page went out with the same query, so a cursor-paginated API returned the first
page N times. These tests pin the cursor contract, and the short-page guard that
stops a page/offset walk from issuing a run of empty requests.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.connectors.http_connector import HTTPConnector, find_cursor, find_records

BASE = "https://api.example.com"


def _cursor_page(records, *, nxt=None):
    body = {"data": records}
    if nxt:
        body["meta"] = {"next_cursor": nxt}
    return httpx.Response(200, json=body)


@pytest.fixture()
def connector():
    return HTTPConnector()


@pytest.mark.asyncio
async def test_cursor_pagination_sends_the_previous_cursor(connector):
    with respx.mock:
        route = respx.get(f"{BASE}/items").mock(
            side_effect=[
                _cursor_page([{"id": 1}], nxt="CUR-1"),
                _cursor_page([{"id": 2}], nxt="CUR-2"),
                _cursor_page([{"id": 2}]),
            ]
        )

        res = await connector.op_execute(
            "request",
            {
                "url": f"{BASE}/items",
                "paginate": True,
                "pagination_type": "cursor",
                "page_size": 1,
                "max_pages": 5,
            },
        )

        assert route.call_count == 3

        queries = [dict(c.request.url.params) for c in route.calls]
        # First page has no cursor; each later page carries the one before it.
        assert "cursor" not in queries[0]
        assert queries[1]["cursor"] == "CUR-1"
        assert queries[2]["cursor"] == "CUR-2"
        assert all(q["limit"] == "1" for q in queries)

        assert len(res["output"]["body"]) == 3
        assert res["output"]["pagination"]["pages_fetched"] == 3
        assert res["output"]["pagination"]["exhausted"] is True
        assert res["output"]["pagination"]["next_cursor"] is None


@pytest.mark.asyncio
async def test_cursor_pagination_stops_when_the_cursor_runs_out(connector):
    """No cursor back means no more pages, so no further requests are made."""
    with respx.mock:
        route = respx.get(f"{BASE}/items").mock(
            return_value=_cursor_page([{"id": 1}])
        )

        res = await connector.op_execute(
            "request",
            {
                "url": f"{BASE}/items",
                "paginate": True,
                "pagination_type": "cursor",
                "max_pages": 50,
            },
        )

        assert route.call_count == 1, "a body with no cursor must end the walk"
        assert res["output"]["pagination"]["pages_fetched"] == 1
        assert res["output"]["pagination"]["exhausted"] is True


@pytest.mark.asyncio
async def test_cursor_path_is_honoured(connector):
    """An API that nests the token somewhere unusual still pages correctly."""
    with respx.mock:
        route = respx.get(f"{BASE}/items").mock(
            side_effect=[
                httpx.Response(200, json={"rows": [{"id": 1}], "links": {"next": "TOK-A"}}),
                httpx.Response(200, json={"rows": [{"id": 2}], "links": {"next": ""}}),
            ]
        )

        await connector.op_execute(
            "request",
            {
                "url": f"{BASE}/items",
                "paginate": True,
                "pagination_type": "cursor",
                "cursor_path": "links.next",
                "max_pages": 5,
            },
        )

        queries = [dict(c.request.url.params) for c in route.calls]
        assert queries[1]["cursor"] == "TOK-A"


@pytest.mark.asyncio
async def test_cursor_param_name_is_configurable(connector):
    with respx.mock:
        route = respx.get(f"{BASE}/items").mock(
            side_effect=[
                httpx.Response(200, json={"data": [{"id": 1}], "next_cursor": "X"}),
                httpx.Response(200, json={"data": [{"id": 2}]}),
            ]
        )

        await connector.op_execute(
            "request",
            {
                "url": f"{BASE}/items",
                "paginate": True,
                "pagination_type": "cursor",
                "cursor_param": "starting_after",
                "max_pages": 5,
            },
        )

        queries = [dict(c.request.url.params) for c in route.calls]
        assert "starting_after" not in queries[0]
        assert queries[1]["starting_after"] == "X"
        assert "cursor" not in queries[1]


@pytest.mark.asyncio
async def test_page_walk_stops_on_a_short_page(connector):
    """A partial final page must not be followed by an empty request."""
    with respx.mock:
        route = respx.get(f"{BASE}/items").mock(
            side_effect=[
                httpx.Response(200, json={"items": [{"id": 1}, {"id": 2}]}),
                httpx.Response(200, json={"items": [{"id": 3}]}),
            ]
        )

        res = await connector.op_execute(
            "request",
            {
                "url": f"{BASE}/items",
                "paginate": True,
                "pagination_type": "page",
                "page_size": 2,
                "max_pages": 10,
            },
        )

        # Page 2 returned 1 of 2 items => last page. A third request never goes out.
        assert route.call_count == 2
        assert res["output"]["pagination"]["pages_fetched"] == 2
        assert res["output"]["pagination"]["exhausted"] is True


@pytest.mark.asyncio
async def test_page_walk_stops_on_an_empty_page(connector):
    with respx.mock:
        route = respx.get(f"{BASE}/items").mock(
            side_effect=[
                httpx.Response(200, json={"items": [{"id": 1}, {"id": 2}]}),
                httpx.Response(200, json={"items": []}),
            ]
        )

        res = await connector.op_execute(
            "request",
            {
                "url": f"{BASE}/items",
                "paginate": True,
                "pagination_type": "page",
                "page_size": 2,
                "max_pages": 10,
            },
        )

        assert route.call_count == 2
        assert res["output"]["pagination"]["exhausted"] is True


@pytest.mark.asyncio
async def test_short_page_stop_can_be_disabled(connector):
    """Opting out keeps the old fixed-count behaviour."""
    with respx.mock:
        route = respx.get(f"{BASE}/items").mock(
            side_effect=[
                httpx.Response(200, json={"items": [{"id": 1}]}),
                httpx.Response(200, json={"items": [{"id": 2}]}),
            ]
        )

        res = await connector.op_execute(
            "request",
            {
                "url": f"{BASE}/items",
                "paginate": True,
                "pagination_type": "page",
                "page_size": 2,
                "max_pages": 2,
                "stop_when_short": False,
            },
        )

        assert route.call_count == 2
        assert res["output"]["pagination"]["pages_fetched"] == 2
        assert res["output"]["pagination"]["exhausted"] is False


@pytest.mark.asyncio
async def test_records_path_is_honoured_for_short_detection(connector):
    """Without a records path an unexpected shape is not mistaken for 'finished'."""
    with respx.mock:
        route = respx.get(f"{BASE}/items").mock(
            return_value=httpx.Response(200, json={"payload": {"rows": []}})
        )

        await connector.op_execute(
            "request",
            {
                "url": f"{BASE}/items",
                "paginate": True,
                "pagination_type": "page",
                "page_size": 2,
                "max_pages": 3,
                "records_path": "payload.rows",
            },
        )

        assert route.call_count == 1


@pytest.mark.asyncio
async def test_single_page_is_untouched_by_pagination(connector):
    """paginate with max_pages=1 behaves exactly like a plain request."""
    with respx.mock:
        route = respx.get(f"{BASE}/items").mock(
            return_value=httpx.Response(200, json={"items": [{"id": 1}]})
        )

        res = await connector.op_execute(
            "request",
            {
                "url": f"{BASE}/items",
                "paginate": True,
                "pagination_type": "cursor",
                "page_size": 3,
                "max_pages": 1,
            },
        )

        assert route.call_count == 1
        params = dict(route.calls.last.request.url.params)
        assert "cursor" not in params
        assert "limit" not in params
        # Body stays a single object rather than being wrapped in a page list.
        assert isinstance(res["output"]["body"], dict)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_find_cursor_probes_the_usual_places():
    assert find_cursor({"next_cursor": "A"}, "") == "A"
    assert find_cursor({"meta": {"next_cursor": "B"}}, "") == "B"
    assert find_cursor({"paging": {"next": {"after": "C"}}}, "") == "C"
    assert find_cursor({"next_url": "https://x/y"}, "") == "https://x/y"


def test_find_cursor_prefers_the_declared_path():
    assert find_cursor({"meta": {"next_cursor": "A"}, "other": "B"}, "other") == "B"


def test_find_cursor_follows_a_declared_path_as_a_whole():
    """A dotted cursor_path is one path, not a list of segments to probe.

    Regression: splitting "links.next" on the dot meant neither "links" nor
    "next" resolved, so a nested cursor was silently reported as end-of-results
    and the page walk stopped after the first request.
    """
    body = {"rows": [{"id": 1}], "links": {"next": "TOK-A"}}
    assert find_cursor(body, "links.next") == "TOK-A"
    assert find_cursor({"a": {"b": {"c": "DEEP"}}}, "a.b.c") == "DEEP"


def test_find_cursor_distinguishes_end_of_results():
    assert find_cursor({"data": []}, "") == ""
    assert find_cursor({"next_cursor": ""}, "") == ""
    assert find_cursor({"next_cursor": None}, "") == ""
    # A boolean "has more" flag is not a cursor.
    assert find_cursor({"has_more": True}, "") == ""


def test_find_cursor_skips_structured_values():
    # A dict/list under a cursor key is pagination metadata, not the token.
    assert find_cursor({"next": {"href": "https://x"}}, "") == ""
    assert find_cursor({"next": {"href": "https://x"}}, "next") == ""


def test_find_records_locates_the_list():
    assert find_records({"items": [1, 2]}, "") == [1, 2]
    assert find_records({"data": {"results": [3]}}, "data.results") == [3]
    assert find_records([1, 2], "") == [1, 2]
    assert find_records({"nope": 1}, "") == []
    assert find_records({"items": "not-a-list"}, "") == []
