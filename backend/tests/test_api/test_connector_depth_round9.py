"""Depth pass 9: GitLab, Linear, Snowflake, Supabase, Typeform, and Resend."""

from __future__ import annotations

import pytest

from app.connectors import ensure_builtin_connectors, get_registry


class _FakeResponse:
    def __init__(self, payload: dict | None = None, headers: dict | None = None) -> None:
        self._payload = payload or {}
        self.headers = headers or {}
        self.status_code = 200
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _FakeHttpxClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    def _next(self, method: str, url: str, **kwargs) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    async def get(self, url, **kwargs):
        return self._next("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return self._next("POST", url, **kwargs)

    async def head(self, url, **kwargs):
        return self._next("HEAD", url, **kwargs)

    async def patch(self, url, **kwargs):
        return self._next("PATCH", url, **kwargs)

    async def delete(self, url, **kwargs):
        return self._next("DELETE", url, **kwargs)


@pytest.fixture(autouse=True)
def _connectors():
    ensure_builtin_connectors()


@pytest.mark.asyncio
async def test_gitlab_branches_and_merge_request(monkeypatch):
    from app.providers.gitlab import GitLabProviderClient

    client = GitLabProviderClient()
    calls = []

    async def fake_request(method, path, creds, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return [{"name": "main"}]
        return {"iid": 7, "title": "Add docs"}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"access_token": "token"}

    branches = await client.list_branches(creds, "acme/app")
    assert branches[0]["name"] == "main"

    mr = await client.create_merge_request(
        creds, "acme/app", "Add docs", "feature", "main", description="Docs",
    )
    assert mr["iid"] == 7
    assert calls[-1][2]["json_body"]["source_branch"] == "feature"


@pytest.mark.asyncio
async def test_linear_teams_and_delete_issue(monkeypatch):
    from app.providers.linear import LinearProviderClient

    client = LinearProviderClient()
    calls = []

    async def fake_gql(creds, query, variables, what, timeout=30.0):
        calls.append((query, variables))
        if "teams" in query:
            return {"teams": {"nodes": [{"id": "t1", "name": "Core"}]}}
        return {"issueDelete": {"success": True}}

    monkeypatch.setattr(client, "_gql", fake_gql)
    creds = {"api_key": "token"}

    teams = await client.list_teams(creds)
    assert teams[0]["name"] == "Core"

    deleted = await client.delete_issue(creds, "i1")
    assert deleted["deleted"] is True
    assert calls[-1][1] == {"id": "i1"}


@pytest.mark.asyncio
async def test_snowflake_list_databases_and_schemas(monkeypatch):
    from app.providers.snowflake import SnowflakeProviderClient

    client = SnowflakeProviderClient()
    calls = []

    async def fake_execute(creds, statement, **kwargs):
        calls.append((statement, kwargs))
        return {"statementHandle": "h1", "data": []}

    monkeypatch.setattr(client, "execute_statement", fake_execute)
    creds = {"account": "acct", "token": "token"}

    databases = await client.list_databases(creds)
    assert databases["statementHandle"] == "h1"
    assert calls[0][0] == "SHOW DATABASES"

    schemas = await client.list_schemas(creds, database="analytics")
    assert schemas["statementHandle"] == "h1"
    assert calls[-1][0] == 'SHOW SCHEMAS IN DATABASE "analytics"'


@pytest.mark.asyncio
async def test_supabase_upsert_and_count(monkeypatch):
    from app.connectors import supabase_connector as module

    fake = _FakeHttpxClient([
        _FakeResponse({"id": 1}),
        _FakeResponse(headers={"content-range": "0-0/42"}),
    ])
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: fake)

    async def fake_url(url: str) -> str:
        return url

    monkeypatch.setattr(module.SupabaseConnector, "_project_url", staticmethod(fake_url))
    conn = module.SupabaseConnector()
    creds = {"url": "https://example.supabase.co", "service_role_key": "key"}
    context = {"credentials": {"supabase": creds}}

    upserted = await conn.op_execute(
        "upsert_row", {"table": "users", "data": {"id": 1}, "on_conflict": "id"}, context,
    )
    assert upserted["data"]["id"] == 1
    assert fake.calls[0][2]["headers"]["Prefer"].startswith("resolution=merge-duplicates")

    counted = await conn.op_execute(
        "count_rows", {"table": "users", "filter": {"active": "eq.true"}}, context,
    )
    assert counted["count"] == 42
    assert fake.calls[-1][0] == "HEAD"


@pytest.mark.asyncio
async def test_typeform_workspaces_and_response(monkeypatch):
    from app.providers.typeform import TypeformProviderClient

    client = TypeformProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "workspaces":
            return {"items": [{"id": "w1", "name": "Marketing"}]}
        return {"response_id": "r1", "answers": []}

    monkeypatch.setattr(client, "request_typeform", fake_request)
    creds = {"token": "token"}

    workspaces = await client.list_workspaces(creds)
    assert workspaces["items"][0]["name"] == "Marketing"

    response = await client.get_response(creds, "form1", "r1")
    assert response["response_id"] == "r1"


@pytest.mark.asyncio
async def test_resend_list_and_cancel_email(monkeypatch):
    from app.connectors import resend_connector as module

    fake = _FakeHttpxClient([
        _FakeResponse({"data": [{"id": "e1"}]}),
        _FakeResponse({"id": "e1", "status": "canceled"}),
    ])
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: fake)
    conn = module.ResendConnector()
    context = {"credentials": {"resend": {"api_key": "key"}}}

    listed = await conn.op_execute("list_emails", {}, context)
    assert listed["data"][0]["id"] == "e1"

    canceled = await conn.op_execute("cancel_email", {"email_id": "e1"}, context)
    assert canceled["status"] == "canceled"
    assert fake.calls[-1][1].endswith("/emails/e1/cancel")


@pytest.mark.asyncio
async def test_depth_round9_connector_routes_map_new_operations(monkeypatch):
    from app.connectors.gitlab_connector import GitLabConnector
    from app.connectors.linear_connector import LinearConnector
    from app.connectors.snowflake_connector import SnowflakeConnector
    from app.connectors.typeform_connector import TypeformConnector

    gitlab = GitLabConnector()

    async def fake_branches(creds, project_id, **kwargs):
        assert project_id == "acme/app"
        return [{"name": "main"}]

    monkeypatch.setattr(gitlab._provider, "list_branches", fake_branches)
    branches = await gitlab.op_execute(
        "list_branches", {"project_id": "acme/app"},
        context={"credentials": {"gitlab": {"access_token": "x"}}},
    )
    assert branches["branches"][0]["name"] == "main"

    linear = LinearConnector()

    async def fake_teams(creds, **kwargs):
        return [{"id": "t1", "name": "Core"}]

    monkeypatch.setattr(linear._provider, "list_teams", fake_teams)
    teams = await linear.op_execute(
        "list_teams", {}, context={"credentials": {"linear": {"api_key": "x"}}},
    )
    assert teams["teams"][0]["name"] == "Core"

    snowflake = SnowflakeConnector()

    async def fake_databases(creds, **kwargs):
        return {"statementHandle": "h1"}

    monkeypatch.setattr(snowflake._provider, "list_databases", fake_databases)
    databases = await snowflake.op_execute(
        "list_databases", {}, context={"credentials": {"snowflake": {"account": "a", "token": "x"}}},
    )
    assert databases["statementHandle"] == "h1"

    typeform = TypeformConnector()

    async def fake_workspaces(creds, **kwargs):
        return {"items": [{"id": "w1"}]}

    monkeypatch.setattr(typeform._provider, "list_workspaces", fake_workspaces)
    workspaces = await typeform.op_execute(
        "list_workspaces", {}, context={"credentials": {"typeform": {"token": "x"}}},
    )
    assert workspaces["items"][0]["id"] == "w1"


def test_depth_round9_definitions_expose_new_operations():
    expected = {
        "gitlab": {"list_branches", "create_merge_request"},
        "linear": {"list_teams", "delete_issue"},
        "snowflake": {"list_databases", "list_schemas"},
        "supabase": {"upsert_row", "count_rows"},
        "typeform": {"list_workspaces", "get_response"},
        "resend": {"list_emails", "cancel_email"},
    }
    for key, operations in expected.items():
        definition = get_registry().get_definition(key)
        assert definition is not None
        assert operations <= set(definition.operations), (key, set(definition.operations))
