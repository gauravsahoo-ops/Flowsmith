"""Batch A/C nodes: date_time, item_lists, markdown_text, html_extract,
crypto_tools, text_splitter, output_parser, embeddings, memory.

Pure-local tests (no network). Memory uses an isolated fakeredis server.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.engine.errors import NodeExecutionError
from app.engine.node_base import MemoryKVStore, NodeContext


def _ctx(**kwargs):
    return NodeContext(
        execution_id="e", workflow_id="wf", logger=logging.getLogger("t"),
        http_client=None, storage=MemoryKVStore(), **kwargs
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ----------------------------------------------------------------------
# date_time
# ----------------------------------------------------------------------

def test_datetime_now_and_parse():
    from app.nodes.date_time import DateTimeNode, DateTimeParams

    node = DateTimeNode()
    now = _run(node.run(_ctx(), DateTimeParams(operation="now"), []))
    assert "now" in now.output_items[0]
    parsed = _run(node.run(
        _ctx(), DateTimeParams(operation="parse", value="2026-01-02T03:04:05"), []
    ))
    assert parsed.output_items[0]["epoch"] > 0
    shifted = _run(node.run(
        _ctx(), DateTimeParams(operation="shift", base="2026-01-01T00:00:00", days=1), []
    ))
    assert "2026-01-02" in shifted.output_items[0]["shifted"]
    diff = _run(node.run(
        _ctx(), DateTimeParams(
            operation="diff", value="2026-01-02T00:00:00",
            start="2026-01-01T00:00:00", unit="days",
        ), []
    ))
    assert diff.output_items[0]["diff"] == 1.0


def test_datetime_bad_parse_raises():
    from app.nodes.date_time import DateTimeNode, DateTimeParams

    with pytest.raises(NodeExecutionError):
        _run(DateTimeNode().run(
            _ctx(), DateTimeParams(operation="parse", value="not-a-date"), []
        ))


# ----------------------------------------------------------------------
# item_lists
# ----------------------------------------------------------------------

def test_item_lists_sort_limit_dedupe_reverse_pluck():
    from app.nodes.item_lists import ItemListsNode, ItemListsParams

    node = ItemListsNode()
    items = [{"n": 2}, {"n": 1}, {"n": 2}]
    out = _run(node.run(_ctx(), ItemListsParams(operation="sort", field="n"), items))
    assert [i["n"] for i in out.output_items] == [1, 2, 2]
    out = _run(node.run(_ctx(), ItemListsParams(operation="limit", limit=2), items))
    assert len(out.output_items) == 2
    out = _run(node.run(_ctx(), ItemListsParams(operation="dedupe", field="n"), items))
    assert len(out.output_items) == 2
    out = _run(node.run(_ctx(), ItemListsParams(operation="reverse"), items))
    assert out.output_items[0] == {"n": 2} and out.output_items[-1] == {"n": 2}
    out = _run(node.run(_ctx(), ItemListsParams(operation="pluck", field="n"), items))
    assert out.output_items == [{"value": 2}, {"value": 1}, {"value": 2}]


# ----------------------------------------------------------------------
# markdown_text
# ----------------------------------------------------------------------

def test_markdown_to_text_and_html():
    from app.nodes.markdown_text import MarkdownTextNode, MarkdownTextParams

    node = MarkdownTextNode()
    out = _run(node.run(_ctx(), MarkdownTextParams(operation="to_text", text="# Hi **there**"), []))
    assert out.output_items[0]["text"] == "Hi there"
    out = _run(node.run(_ctx(), MarkdownTextParams(operation="to_html", text="# Hi"), []))
    assert "<h1>Hi</h1>" in out.output_items[0]["html"]


# ----------------------------------------------------------------------
# html_extract
# ----------------------------------------------------------------------

def test_html_extract_text_links_images():
    from app.nodes.html_extract import HtmlExtractNode, HtmlExtractParams

    node = HtmlExtractNode()
    html = '<p>Hello <a href="https://x.com">link</a></p><img src="https://x.com/i.png">'
    out = _run(node.run(_ctx(), HtmlExtractParams(operation="text", html=html), []))
    assert "Hello" in out.output_items[0]["text"] and "script" not in out.output_items[0]
    out = _run(node.run(_ctx(), HtmlExtractParams(operation="links", html=html), []))
    assert out.output_items == [{"href": "https://x.com", "text": "link"}]
    out = _run(node.run(_ctx(), HtmlExtractParams(operation="images", html=html), []))
    assert out.output_items == [{"src": "https://x.com/i.png"}]


# ----------------------------------------------------------------------
# crypto_tools
# ----------------------------------------------------------------------

def test_crypto_hash_hmac_base64_uuid_token():
    from app.nodes.crypto_tools import CryptoToolsNode, CryptoToolsParams

    node = CryptoToolsNode()
    out = _run(node.run(_ctx(), CryptoToolsParams(operation="hash", text="abc"), []))
    assert out.output_items[0]["digest"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    out = _run(node.run(_ctx(), CryptoToolsParams(operation="base64_encode", text="hi"), []))
    b64 = out.output_items[0]["base64"]
    out = _run(node.run(_ctx(), CryptoToolsParams(operation="base64_decode", text=b64), []))
    assert out.output_items[0]["text"] == "hi"
    out = _run(node.run(_ctx(), CryptoToolsParams(operation="uuid"), []))
    assert len(out.output_items[0]["uuid"]) == 36
    out = _run(node.run(_ctx(), CryptoToolsParams(operation="hmac", text="m", key="k"), []))
    assert len(out.output_items[0]["hmac"]) == 64


def test_crypto_bad_algorithm_raises():
    from app.nodes.crypto_tools import CryptoToolsNode, CryptoToolsParams

    with pytest.raises(NodeExecutionError):
        _run(CryptoToolsNode().run(_ctx(), CryptoToolsParams(operation="hash", text="x", algorithm="rot13"), []))


# ----------------------------------------------------------------------
# text_splitter
# ----------------------------------------------------------------------

def test_text_splitter_characters_overlap():
    from app.nodes.text_splitter import TextSplitterNode, TextSplitterParams

    node = TextSplitterNode()
    text = "abcdefghij" * 12  # 120 chars
    out = _run(node.run(
        _ctx(), TextSplitterParams(mode="characters", text=text, chunk_size=50, overlap=10), []
    ))
    chunks = [i["chunk"] for i in out.output_items]
    assert chunks[0] == text[:50] and chunks[1] == text[40:90]
    assert all(i["total"] == len(chunks) for i in out.output_items)


# ----------------------------------------------------------------------
# output_parser
# ----------------------------------------------------------------------

def test_output_parser_json_lines_fields():
    from app.nodes.output_parser import OutputParserNode, OutputParserParams

    node = OutputParserNode()
    out = _run(node.run(
        _ctx(), OutputParserParams(mode="json", text='```json\n{"a": 1}\n```'), []
    ))
    assert out.output_items == [{"a": 1}]
    out = _run(node.run(_ctx(), OutputParserParams(mode="lines", text="x\ny\n"), []))
    assert [i["line"] for i in out.output_items] == ["x", "y"]
    out = _run(node.run(
        _ctx(), OutputParserParams(mode="fields", text='{"a": 1, "b": 2}', fields=["a"]), []
    ))
    assert out.output_items == [{"a": 1}]


def test_output_parser_strict_raises():
    from app.nodes.output_parser import OutputParserNode, OutputParserParams

    with pytest.raises(NodeExecutionError):
        _run(OutputParserNode().run(_ctx(), OutputParserParams(mode="json", text="nope", strict=True), []))


# ----------------------------------------------------------------------
# embeddings (dev fallback when AI extra missing)
# ----------------------------------------------------------------------

def test_embeddings_returns_vectors():
    from app.nodes.embeddings import EmbeddingsNode, EmbeddingsParams

    node = EmbeddingsNode()
    out = _run(node.run(_ctx(), EmbeddingsParams(texts=["hello", "world"]), []))
    assert len(out.output_items) == 2
    assert all(i["dim"] == len(i["embedding"]) > 0 for i in out.output_items)


# ----------------------------------------------------------------------
# rss_feed (mocked HTTP, no network)
# ----------------------------------------------------------------------

_RSS_SAMPLE = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>A</title><link>https://x.com/a</link><description>da</description><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item>
<item><title>B</title><link>https://x.com/b</link><description>db</description></item>
</channel></rss>"""


def _mock_http_client(payload: bytes, status: int = 200):
    import httpx

    def handler(request):
        return httpx.Response(status, content=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_rss_feed_parses_items():
    import asyncio

    from app.nodes.rss_feed import RssFeedNode, RssFeedParams

    async def go():
        client = _mock_http_client(_RSS_SAMPLE.encode())
        try:
            ctx = _ctx()
            ctx.http_client = client
            node = RssFeedNode()
            out = await node.run(ctx, RssFeedParams(url="https://x.com/feed.xml", limit=5), [])
            return out
        finally:
            await client.aclose()

    out = asyncio.new_event_loop().run_until_complete(go())
    assert [i["title"] for i in out.output_items] == ["A", "B"]
    assert out.output_items[0]["link"] == "https://x.com/a"


def test_rss_feed_rejects_bad_url_and_http_error():
    import asyncio

    from app.engine.errors import NodeExecutionError
    from app.nodes.rss_feed import RssFeedNode, RssFeedParams

    async def go_bad_url():
        client = _mock_http_client(b"")
        try:
            ctx = _ctx()
            ctx.http_client = client
            with pytest.raises(NodeExecutionError):
                await RssFeedNode().run(ctx, RssFeedParams(url="ftp://x.com/f"), [])
        finally:
            await client.aclose()

    async def go_http_error():
        client = _mock_http_client(b"nope", status=500)
        try:
            ctx = _ctx()
            ctx.http_client = client
            with pytest.raises(NodeExecutionError):
                await RssFeedNode().run(ctx, RssFeedParams(url="https://x.com/f"), [])
        finally:
            await client.aclose()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(go_bad_url())
    loop.run_until_complete(go_http_error())

# ----------------------------------------------------------------------
# email_read (pure parsing + faked IMAP, no network)
# ----------------------------------------------------------------------

_RAW_MAIL = b"""From: ada@x.com\r\nTo: bob@x.com\r\nSubject: Hi\r\nDate: Mon, 01 Jan 2024 00:00:00 +0000\r\nMessage-ID: <m1@x.com>\r\nContent-Type: multipart/alternative; boundary="b"\r\n\r\n--b\r\nContent-Type: text/plain\r\n\r\nhello plain\r\n--b\r\nContent-Type: text/html\r\n\r\n<p>hello html</p>\r\n--b--\r\n"""


def test_email_parse_prefers_plain_text():
    from app.nodes.email_read import _parse_message

    parsed = _parse_message(_RAW_MAIL)
    assert parsed["subject"] == "Hi"
    assert parsed["from"] == "ada@x.com"
    assert parsed["body_text"].strip() == "hello plain"
    assert parsed["message_id"] == "<m1@x.com>"


def test_email_read_missing_creds_raises():
    from app.engine.errors import NodeExecutionError
    from app.nodes.email_read import EmailReadNode, EmailReadParams

    with pytest.raises(NodeExecutionError):
        _run(EmailReadNode().run(_ctx(), EmailReadParams(), []))


def test_email_read_fetch_via_fake_imap(monkeypatch):
    import app.nodes.email_read as mod
    from app.nodes.email_read import EmailReadNode, EmailReadParams

    seen = {}

    class FakeIMAP:
        def __init__(self, host, port, timeout=None):
            seen["host"] = host

        def login(self, user, password):
            assert user == "u" and password == "p"

        def select(self, folder, readonly=True):
            return ("OK", [b"1"])

        def search(self, charset, criteria):
            assert criteria == "UNSEEN"
            return ("OK", [b"1 2"])

        def fetch(self, num, spec):
            return ("OK", [(b"hdr", _RAW_MAIL)])

        def close(self):
            pass

        def logout(self):
            pass

    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", FakeIMAP)
    node = EmailReadNode()
    ctx = _ctx(credentials={"imap": {"host": "imap.x.com", "username": "u", "password": "p"}})
    out = _run(node.run(ctx, EmailReadParams(limit=5), []))
    assert len(out.output_items) == 2
    assert out.output_items[0]["subject"] == "Hi"
    assert seen["host"] == "imap.x.com"


# ----------------------------------------------------------------------
# memory (isolated fakeredis)
# ----------------------------------------------------------------------

@pytest.fixture
def _fake_redis(monkeypatch):
    import fakeredis.aioredis

    server = fakeredis.aioredis.FakeServer()
    monkeypatch.setattr(
        "redis.asyncio.from_url",
        lambda uri, **kw: fakeredis.aioredis.FakeRedis.from_url(uri, server=server, **kw),
    )


def test_memory_push_recall_clear(_fake_redis):
    from app.nodes.memory import MemoryNode, MemoryParams

    node = MemoryNode()
    ctx = _ctx(workspace_id="ws1", credentials={"redis": {"uri": "redis://fake:6379/0"}})
    push = _run(node.run(ctx, MemoryParams(operation="push", session_id="s1", content="hello"), []))
    assert push.output_items[0]["pushed"] is True
    recall = _run(node.run(ctx, MemoryParams(operation="recall", session_id="s1"), []))
    assert recall.output_items[0]["content"] == "hello"
    clear = _run(node.run(ctx, MemoryParams(operation="clear", session_id="s1"), []))
    assert clear.output_items[0]["cleared"] is True
    recall2 = _run(node.run(ctx, MemoryParams(operation="recall", session_id="s1"), []))
    assert recall2.output_items[0].get("empty") is True
