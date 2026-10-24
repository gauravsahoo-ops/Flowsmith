"""Depth pass 3: GitHub, Jira, Notion, MongoDB, SQL, and S3 operations."""

from __future__ import annotations

import base64

import pytest

from app.connectors import ensure_builtin_connectors, get_registry
from tests.test_api._connector_fakes import empty_response, json_response


@pytest.fixture(autouse=True)
def _connectors():
    ensure_builtin_connectors()


@pytest.mark.asyncio
async def test_github_branches_file_contents_and_pull_request(monkeypatch):
    from app.providers.github import GitHubProviderClient

    client = GitHubProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path.endswith("/branches"):
            page = (kwargs.get("params") or {}).get("page")
            if page == 1:
                return json_response(200, [
                    {"name": "main", "protected": True, "commit": {"sha": "a1"}},
                    {"name": "dev", "protected": False, "commit": {"sha": "b2"}},
                ])
            return json_response(200, [
                {"name": "feature", "protected": False, "commit": {"sha": "c3"}},
            ])
        if "/contents/" in path:
            return json_response(200, {
                "type": "file",
                "name": "README.md",
                "path": "docs/README.md",
                "sha": "f1",
                "size": 5,
                "encoding": "base64",
                "content": base64.b64encode(b"hello").decode("ascii"),
                "download_url": "https://example.test/README.md",
            })
        if path.endswith("/pulls"):
            return json_response(201, {
                "number": 7,
                "html_url": "https://github.test/o/r/pull/7",
                "state": "open",
                "head": {"ref": "feature"},
                "base": {"ref": "main"},
            })
        raise AssertionError(f"unexpected GitHub call: {method} {path}")

    monkeypatch.setattr(client, "request_github", fake_request)
    creds = {"access_token": "token"}

    branches = await client.list_branches(creds, "acme", "app", per_page=2, max_pages=2)
    assert [b["name"] for b in branches["branches"]] == ["main", "dev", "feature"]
    assert branches["count"] == 3
    assert branches["branches"][0]["protected"] is True

    file_result = await client.get_file_contents(creds, "acme", "app", "docs/README.md")
    assert file_result["content"] == "hello"
    assert file_result["type"] == "file"

    pr = await client.create_pull_request(
        creds, "acme", "app", "Add docs", head="feature", base="main", body="Docs",
    )
    assert pr["number"] == 7
    assert pr["head"] == "feature"
    assert calls[-1][2]["json_body"]["base"] == "main"


@pytest.mark.asyncio
async def test_jira_user_transitions_and_transition(monkeypatch):
    from app.providers.jira import JiraProviderClient

    client = JiraProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/myself":
            return json_response(200, {
                "accountId": "acc-1",
                "displayName": "Ada Lovelace",
                "emailAddress": "ada@example.com",
                "active": True,
                "timeZone": "UTC",
            })
        if path.endswith("/transitions") and method == "GET":
            return json_response(200, {"transitions": [
                {"id": "31", "name": "Start progress", "to": {"name": "In Progress"}},
                {"id": "41", "name": "Done", "to": {"name": "Done"}},
            ]})
        if path.endswith("/transitions") and method == "POST":
            return empty_response(204)
        raise AssertionError(f"unexpected Jira call: {method} {path}")

    monkeypatch.setattr(client, "request_jira", fake_request)
    creds = {"site": "https://acme.atlassian.net", "email": "ada@example.com", "api_token": "token"}

    me = await client.get_myself(creds)
    assert me["account_id"] == "acc-1"
    assert me["display_name"] == "Ada Lovelace"

    transitions = await client.list_transitions(creds, "PROJ-123")
    assert transitions["count"] == 2
    assert transitions["transitions"][1]["to_status"] == "Done"

    moved = await client.transition_issue(creds, "PROJ-123", "31")
    assert moved["success"] is True
    assert calls[-1][2]["json_body"] == {"transition": {"id": "31"}}


@pytest.mark.asyncio
async def test_notion_search_and_block_children(monkeypatch):
    from app.providers.notion import NotionProviderClient

    client = NotionProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/search":
            return json_response(200, {
                "results": [{
                    "object": "page",
                    "id": "page-1",
                    "url": "https://notion.test/page-1",
                    "last_edited_time": "2026-01-01T00:00:00.000Z",
                    "properties": {
                        "Name": {
                            "type": "title",
                            "title": [{"plain_text": "Roadmap"}],
                        }
                    },
                }],
                "has_more": False,
                "next_cursor": None,
            })
        if path.endswith("/children"):
            return json_response(200, {
                "results": [{"id": "block-1", "type": "paragraph"}],
                "has_more": False,
                "next_cursor": None,
            })
        raise AssertionError(f"unexpected Notion call: {method} {path}")

    monkeypatch.setattr(client, "request_notion", fake_request)
    creds = {"integration_token": "secret_token"}

    found = await client.search(creds, query="Roadmap")
    assert found["count"] == 1
    assert found["results"][0]["title"] == "Roadmap"

    children = await client.get_block_children(
        creds, "12345678-1234-1234-1234-123456789012",
    )
    assert children["count"] == 1
    assert children["blocks"][0]["id"] == "block-1"
    assert calls[-1][0] == "GET"


@pytest.mark.asyncio
async def test_mongodb_list_collections_and_create_index(monkeypatch):
    from app.providers import mongodb as mongodb_module

    class FakeError(Exception):
        pass

    class FakeCollection:
        def create_index(self, spec, unique=False):
            assert spec == [("email", 1)]
            assert unique is True
            return "email_1"

    class FakeDatabase:
        def list_collection_names(self):
            return ["users", "audit"]

        def __getitem__(self, name):
            assert name == "users"
            return FakeCollection()

    class FakeClient:
        def __init__(self, uri, **kwargs):
            assert uri == "mongodb://localhost:27017"
            self.closed = False

        def __getitem__(self, name):
            assert name == "appdb"
            return FakeDatabase()

        def close(self):
            self.closed = True

    class FakePyMongo:
        MongoClient = FakeClient

    monkeypatch.setattr(
        mongodb_module, "_require_pymongo", lambda: (FakePyMongo, FakeError),
    )
    client = mongodb_module.MongoProviderClient()
    creds = {"uri": "mongodb://localhost:27017"}

    collections = await client.list_collections(creds, "appdb")
    assert collections["collections"] == ["audit", "users"]
    assert collections["count"] == 2

    index = await client.create_index(
        creds, "appdb", "users", {"email": 1}, unique=True,
    )
    assert index["index"] == "email_1"
    assert index["success"] is True


def test_sql_describe_table_reports_columns_keys_and_indexes():
    from sqlalchemy import create_engine, text

    from app.providers.sql_provider import _describe_table

    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE orgs (id INTEGER PRIMARY KEY)"))
        conn.execute(text(
            "CREATE TABLE users ("
            "id INTEGER PRIMARY KEY, "
            "email VARCHAR(255) NOT NULL, "
            "org_id INTEGER, "
            "FOREIGN KEY (org_id) REFERENCES orgs(id))"
        ))
        conn.execute(text("CREATE INDEX ix_users_email ON users (email)"))

    result = _describe_table(engine, "users")
    assert result["table"] == "users"
    assert [c["name"] for c in result["columns"]] == ["id", "email", "org_id"]
    assert result["primary_key"] == ["id"]
    assert result["columns"][0]["primary_key"] is True
    assert result["columns"][1]["nullable"] is False
    assert any(index["name"] == "ix_users_email" for index in result["indexes"])
    assert any(fk["referred_table"] == "orgs" for fk in result["foreign_keys"])
    engine.dispose()


@pytest.mark.asyncio
async def test_sql_describe_table_rejects_unsafe_identifier():
    from app.connectors import ConnectorError, ConnectorErrorCode
    from app.providers.postgres import PostgresProviderClient

    client = PostgresProviderClient()
    with pytest.raises(ConnectorError) as exc_info:
        await client.describe_table({"dsn": "postgresql://user:pass@localhost/db"}, "users; DROP TABLE users")
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value


@pytest.mark.asyncio
async def test_s3_head_object_returns_real_metadata():
    import httpx
    import respx

    from app.connectors.s3_connector import S3Connector

    conn = S3Connector()
    await conn.connect({
        "access_key_id": "AKIDEXAMPLE",
        "secret_access_key": "secret",
        "bucket_name": "my-test-bucket",
        "region": "us-east-1",
    })

    with respx.mock:
        route = respx.head(
            "https://my-test-bucket.s3.amazonaws.com/test.txt"
        ).mock(return_value=httpx.Response(
            200,
            headers={
                "Content-Length": "11",
                "ETag": '"abc123"',
                "Content-Type": "text/plain",
                "Last-Modified": "Wed, 01 Jan 2026 00:00:00 GMT",
                "x-amz-meta-owner": "ada",
            },
        ))
        result = await conn.op_execute("head_object", {"key": "test.txt"})

    assert route.called
    request = route.calls.last.request
    assert request.headers["Authorization"].startswith("AWS4-HMAC-SHA256")
    item = result["output"][0]
    assert item["exists"] is True
    assert item["status"] == "found"
    assert item["size_bytes"] == 11
    assert item["etag"] == '"abc123"'
    assert item["metadata"] == {"owner": "ada"}

    with respx.mock:
        respx.head(
            "https://my-test-bucket.s3.amazonaws.com/missing.txt"
        ).mock(return_value=httpx.Response(404))
        missing = await conn.op_execute("head_object", {"key": "missing.txt"})
    assert missing["output"][0]["status"] == "not_found"
    assert missing["output"][0]["exists"] is False


@pytest.mark.asyncio
async def test_depth_round3_connector_routes_map_new_operations(monkeypatch):
    from app.connectors.github_connector import GitHubConnector
    from app.connectors.jira_connector import JiraConnector
    from app.connectors.mongodb_connector import MongoDBConnector
    from app.connectors.notion_connector import NotionConnector
    from app.connectors.postgres_connector import PostgresConnector

    github = GitHubConnector()

    async def fake_branches(creds, owner, repo, **kwargs):
        assert (owner, repo) == ("acme", "app")
        return {"branches": [{"name": "main"}], "count": 1}

    monkeypatch.setattr(github._provider, "list_branches", fake_branches)
    branches = await github.op_execute(
        "list_branches", {"owner": "acme", "repo": "app"},
        context={"credentials": {"github": {"access_token": "token"}}},
    )
    assert branches["branches"][0]["name"] == "main"

    jira = JiraConnector()

    async def fake_myself(creds, **kwargs):
        return {"account_id": "acc-1"}

    monkeypatch.setattr(jira._provider, "get_myself", fake_myself)
    me = await jira.op_execute(
        "get_myself", {},
        context={"credentials": {"jira": {"site": "https://acme.atlassian.net"}}},
    )
    assert me["account_id"] == "acc-1"

    notion = NotionConnector()

    async def fake_search(creds, **kwargs):
        assert kwargs["query"] == "Roadmap"
        return {"results": [{"id": "page-1"}], "count": 1}

    monkeypatch.setattr(notion._provider, "search", fake_search)
    found = await notion.op_execute(
        "search", {"query": "Roadmap"},
        context={"credentials": {"notion": {"integration_token": "token"}}},
    )
    assert found["count"] == 1

    mongo = MongoDBConnector()

    async def fake_index(creds, database, collection, keys, **kwargs):
        assert (database, collection, keys) == ("appdb", "users", {"email": 1})
        return {"index": "email_1", "success": True}

    monkeypatch.setattr(mongo._provider, "create_index", fake_index)
    index = await mongo.op_execute(
        "create_index",
        {"database": "appdb", "collection": "users", "keys": {"email": 1}},
        context={"credentials": {"mongodb": {"uri": "mongodb://localhost"}}},
    )
    assert index["index"] == "email_1"

    postgres = PostgresConnector()

    async def fake_describe(creds, table, schema=None):
        assert (table, schema) == ("users", "public")
        return {"table": table, "schema": schema, "columns": []}

    monkeypatch.setattr(postgres._provider, "describe_table", fake_describe)
    described = await postgres.op_execute(
        "describe_table", {"table": "users", "schema": "public"},
        context={"credentials": {"postgres": {"dsn": "postgresql://localhost/db"}}},
    )
    assert described["schema"] == "public"


def test_depth_round3_definitions_expose_new_operations():
    expected = {
        "github": {"list_branches", "get_file_contents", "create_pull_request"},
        "jira": {"get_myself", "list_transitions", "transition_issue"},
        "notion": {"search", "get_block_children"},
        "mongodb": {"list_collections", "create_index"},
        "postgres": {"describe_table"},
        "mysql": {"describe_table"},
        "s3": {"head_object"},
    }
    for key, operations in expected.items():
        definition = get_registry().get_definition(key)
        assert definition is not None
        assert operations <= set(definition.operations), (key, set(definition.operations))
