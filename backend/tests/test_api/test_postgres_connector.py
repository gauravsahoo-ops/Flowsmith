"""PostgreSQL connector tests (Phase 11 business connectors).

The SQL seam is ``sql_provider.create_engine``: a fake engine records
the statement and returns canned rows. Proves:

- query returns rows; execute returns affected_rows
- DSN scheme allowlist (mysql:// DSN on a postgres credential rejected)
- missing credential -> NOT_CONFIGURED
- full-stack workflow run with the secret never leaking into the record
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api.conftest import auth_headers, register


class FakeSQLResult:
    def __init__(self, rows: list[dict] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def returns_rows(self) -> bool:
        return bool(self._rows)

    def fetchmany(self, n: int):
        return [FakeRow(r) for r in self._rows[:n]]


class FakeRow:
    def __init__(self, mapping: dict[str, Any]) -> None:
        self._mapping = mapping


class FakeConnection:
    def __init__(self, engine: "FakeEngine") -> None:
        self._engine = engine

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        pass

    def execute(self, statement, params=None):  # noqa: ANN001
        self._engine.statements.append((str(statement), dict(params or {})))
        return self._engine.result

    def commit(self) -> None:
        self._engine.commits += 1


class FakeEngine:
    def __init__(self, result: FakeSQLResult) -> None:
        self.result = result
        self.statements: list[tuple[str, dict]] = []
        self.commits = 0
        self.disposed = False

    def connect(self) -> FakeConnection:
        return FakeConnection(self)

    def dispose(self) -> None:
        self.disposed = True


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_query_returns_rows(monkeypatch):
    from app.providers import sql_provider

    engine = FakeEngine(FakeSQLResult(rows=[{"id": 1, "email": "a@b.com"}]))
    monkeypatch.setattr(sql_provider, "create_engine", lambda dsn, **kw: engine)

    async def run():
        from app.providers.postgres import PostgresProviderClient

        return await PostgresProviderClient().query(
            {"dsn": "postgresql://u:p@localhost:5432/db"}, "SELECT id, email FROM users"
        )

    import asyncio

    out = asyncio.new_event_loop().run_until_complete(run())
    assert out["count"] == 1
    assert out["rows"][0]["email"] == "a@b.com"
    # Parameterised via text() binding — no interpolation of user values.
    assert "SELECT id, email FROM users" in engine.statements[0][0]
    assert engine.disposed is True


def test_execute_reports_affected_rows_and_commits(monkeypatch):
    from app.providers import sql_provider

    engine = FakeEngine(FakeSQLResult(rowcount=3))
    monkeypatch.setattr(sql_provider, "create_engine", lambda dsn, **kw: engine)

    async def run():
        from app.providers.postgres import PostgresProviderClient

        return await PostgresProviderClient().execute(
            {"dsn": "postgresql://u:p@localhost/db"},
            "UPDATE users SET active = :active",
            {"active": True},
        )

    import asyncio

    out = asyncio.new_event_loop().run_until_complete(run())
    assert out["affected_rows"] == 3
    assert engine.commits == 1
    assert engine.statements[0][1] == {"active": True}


def test_scheme_allowlist_blocks_cross_product_dsn():
    from app.providers.postgres import PostgresProviderClient

    import asyncio

    async def run():
        await PostgresProviderClient().query(
            {"dsn": "mysql://root@localhost/sneaky"}, "SELECT 1"
        )

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
        raise AssertionError("cross-product DSN should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)
        assert "must start with" in str(exc)
    finally:
        loop.close()


def test_missing_credential_is_not_configured():
    from app.providers.postgres import PostgresProviderClient

    import asyncio

    async def run():
        await PostgresProviderClient().query({}, "SELECT 1")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
        raise AssertionError("missing dsn should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)
    finally:
        loop.close()


# ----------------------------------------------------------------------
# Full stack: API -> queue -> worker -> engine -> connector
# ----------------------------------------------------------------------

PG_SECRET_DSN = "postgresql://svc:SUPER_SECRET_PW@db.internal:5432/prod"


def _setup(client):
    return auth_headers(register(client)["token"])


def test_full_stack_postgres_query(client, monkeypatch):
    from app.providers import sql_provider

    headers = _setup(client)
    resp = client.post(
        "/api/credentials",
        json={"name": "PG Prod", "type": "postgres", "data": {"dsn": PG_SECRET_DSN}},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    cred_id = resp.json()["data"]["id"]

    wf = {
        "id": "wf_pg",
        "name": "PG Query",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "pg",
                "type": "postgres",
                "parameters": {
                    "operation": "query",
                    "sql": "SELECT id FROM accounts WHERE status = :status",
                    "params": {"status": "{{ $json.status }}"},
                },
                "credentials": {"postgres": cred_id},
            },
        ],
        "connections": [{"source": "trigger", "target": "pg"}],
        "settings": {},
    }
    resp = client.post("/api/workflows", json=wf, headers=headers)
    assert resp.status_code == 201, resp.text

    engine = FakeEngine(FakeSQLResult(rows=[{"id": 7}]))
    monkeypatch.setattr(sql_provider, "create_engine", lambda dsn, **kw: engine)

    resp = client.post("/api/workflows/wf_pg/run", json={"data": {"status": "active"}}, headers=headers)
    assert resp.status_code == 202, resp.text
    execution_id = resp.json()["data"]["execution_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("running", "queued", "cancelling"):
            break
        time.sleep(0.05)
    assert data["status"] == "success", data.get("error")
    outputs = data["results"]["outputs"]["pg"]["main"]
    assert outputs[0]["count"] == 1 and outputs[0]["rows"][0]["id"] == 7

    # The resolved parameter arrived as a bound value, not interpolated.
    assert engine.statements[0][1] == {"status": "active"}

    # The DSN secret never leaks into the execution record.
    raw = json.dumps(data, default=str)
    assert "SUPER_SECRET_PW" not in raw
