"""Microsoft Dynamics 365 connector: @odata.nextLink paging and resume.

Dataverse pages with an opaque `@odata.nextLink` that points back at the
instance that produced it. These tests pin three things that are easy to get
wrong and silent when they break:

  * the link is followed only while the caller asked for every page,
  * the absolute link is reduced to a path before the HTTP layer re-prefixes
    the instance URL (otherwise the two concatenate into an invalid URL),
  * a run can resume from a link it handed back earlier.

Every assertion is backed by a request captured from the mock transport.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.dynamics_crm_connector import DynamicsCrmConnector

INSTANCE = "https://org.crm.dynamics.com"
API = f"{INSTANCE}/api/data/v9.2"

# access_token + a future expires_at short-circuits token minting, so the mock
# transport below only ever sees the Dataverse calls themselves.
CREDS = {
    "instance_url": INSTANCE,
    "access_token": "tok-0000",
    "expires_at": 4102444800.0,  # 2100-01-01
}
CTX = {"credentials": {"dynamics_crm": CREDS}}


def _page(records, *, next_after=None):
    body: dict = {"value": records}
    if next_after:
        body["@odata.nextLink"] = f"{API}/contacts?$skiptoken={next_after}"
    return httpx.Response(200, json=body)


@pytest.fixture()
def connector():
    return DynamicsCrmConnector()


@pytest.mark.asyncio
async def test_single_page_does_not_emit_a_cursor(connector):
    with respx.mock:
        route = respx.get(f"{API}/contacts").mock(return_value=_page([{"contactid": "a"}]))

        out = await connector.op_execute("query", {"entity": "contacts"}, context=CTX)

        assert route.call_count == 1
        # The absolute instance URL was NOT double-prefixed onto the path.
        assert str(route.calls.last.request.url).startswith(f"{API}/contacts")

        assert out["count"] == 1
        assert out["records"] == [{"contactid": "a"}]
        assert out["has_more"] is False
        assert out["next_link"] is None


@pytest.mark.asyncio
async def test_next_link_is_followed_across_pages(connector):
    with respx.mock:
        route = respx.get(url__regex=r".*/api/data/v9\.2/contacts.*").mock(
            side_effect=[
                _page([{"contactid": "a"}], next_after="PAGE2"),
                _page([{"contactid": "b"}], next_after="PAGE3"),
                _page([{"contactid": "c"}]),
            ]
        )

        out = await connector.op_execute("query", {"entity": "contacts"}, context=CTX)

        assert route.call_count == 3

        # Every requested URL is a well-formed path on the instance, never a
        # scheme-relative or doubled host.
        urls = [str(c.request.url) for c in route.calls]
        assert all(u.startswith(f"{INSTANCE}/api/data/v9.2/contacts") for u in urls), urls
        assert "$skiptoken=PAGE2" in urls[1]
        assert "$skiptoken=PAGE3" in urls[2]

        assert out["records"] == [{"contactid": "a"}, {"contactid": "b"}, {"contactid": "c"}]
        assert out["count"] == 3
        assert out["pages_fetched"] == 3
        assert out["has_more"] is False
        assert out["next_link"] is None


@pytest.mark.asyncio
async def test_single_page_stops_even_when_more_exist(connector):
    """return_all=False fetches one page and hands back the cursor."""
    with respx.mock:
        route = respx.get(f"{API}/contacts").mock(
            return_value=_page([{"contactid": "a"}], next_after="PAGE2")
        )

        out = await connector.op_execute(
            "query", {"entity": "contacts", "return_all": False}, context=CTX
        )

        assert route.call_count == 1
        assert out["has_more"] is True
        assert out["next_link"].endswith("$skiptoken=PAGE2")
        assert out["pages_fetched"] == 1
        assert out["records"] == [{"contactid": "a"}]


@pytest.mark.asyncio
async def test_resume_from_handed_back_cursor(connector):
    """An 'after' cursor skips straight to that page without replaying page 1."""
    with respx.mock:
        route = respx.get(url__regex=r".*").mock(return_value=_page([{"contactid": "z"}]))

        out = await connector.op_execute(
            "query",
            {"entity": "contacts", "return_all": False, "after": f"{API}/contacts?$skiptoken=RESUME"},
            context=CTX,
        )

        assert route.call_count == 1
        requested = str(route.calls.last.request.url)
        # Resume URL is not doubled onto the instance URL.
        assert requested.count(INSTANCE) == 1
        assert "$skiptoken=RESUME" in requested
        assert out["records"] == [{"contactid": "z"}]


@pytest.mark.asyncio
async def test_max_pages_is_a_hard_stop(connector):
    """A cursor that always points onward must not spin forever."""

    def endless(*_args, **_kwargs):
        return _page([{"contactid": "x"}], next_after="ALWAYS")

    with respx.mock:
        route = respx.get(url__regex=r".*/contacts.*").mock(side_effect=endless)

        out = await connector.op_execute(
            "query", {"entity": "contacts", "max_pages": 3}, context=CTX
        )

        assert route.call_count == 3
        assert out["pages_fetched"] == 3
        assert out["has_more"] is True
        assert out["next_link"].endswith("$skiptoken=ALWAYS")


@pytest.mark.asyncio
async def test_fetchxml_is_accepted_under_both_spellings(connector):
    """The published schema names it `fetchXml`; the model attribute is snake_case."""
    fetch = "<fetch top='5'><entity name='contact'/></fetch>"

    with respx.mock:
        # fetchXml queries are requested verbatim against the entity set.
        route = respx.get(url__regex=r".*contacts\?fetchXml=.*").mock(
            return_value=_page([{"contactid": "f"}])
        )

        camel = await connector.op_execute(
            "query", {"entity": "contacts", "fetchXml": fetch}, context=CTX
        )
        snake = await connector.op_execute(
            "query", {"entity": "contacts", "fetch_xml": fetch}, context=CTX
        )

        assert route.call_count == 2, "both spellings must reach the provider"
        assert camel["records"] == [{"contactid": "f"}]
        assert snake["records"] == [{"contactid": "f"}]
        # The raw FetchXML made it into the query string rather than being dropped.
        assert "fetchXml=" in str(route.calls.last.request.url)


@pytest.mark.asyncio
async def test_page_size_is_sent_as_top(connector):
    with respx.mock:
        route = respx.get(f"{API}/accounts").mock(return_value=_page([]))

        await connector.op_execute(
            "query", {"entity": "accounts", "page_size": 250, "return_all": False}, context=CTX
        )

        assert route.calls.last.request.url.params["$top"] == "250"


@pytest.mark.asyncio
async def test_missing_credentials_raises_before_any_request(connector):
    with respx.mock:
        route = respx.get(url__regex=r".*").mock(return_value=_page([]))

        with pytest.raises(ConnectorError) as exc:
            await connector.op_execute("query", {"entity": "contacts"}, context={})

        assert exc.value.code == ConnectorErrorCode.NOT_CONFIGURED.value
        assert route.call_count == 0


@pytest.mark.asyncio
async def test_provider_error_is_translated_not_swallowed(connector):
    with respx.mock:
        respx.get(f"{API}/contacts").mock(
            return_value=httpx.Response(
                403,
                json={"error": {"message": "You do not have the required privilege."}},
            )
        )

        with pytest.raises(ConnectorError) as exc:
            await connector.op_execute("query", {"entity": "contacts"}, context=CTX)

        assert exc.value.code == ConnectorErrorCode.AUTH_FAILED.value
        assert "required privilege" in str(exc.value)
