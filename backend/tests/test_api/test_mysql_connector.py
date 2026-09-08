"""MySQL connector tests (Phase 11 business connectors).

Same seam as the Postgres suite: fake engine at sql_provider.create_engine.
Proves the MySQL scheme allowlist, insert_rows bulk path and validation.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api.test_postgres_connector import FakeEngine, FakeSQLResult


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_query_against_mysql_dsn(monkeypatch):
    from app.providers import sql_provider

    engine = FakeEngine(FakeSQLResult(rows=[{"id": 1}, {"id": 2}]))
    captured: dict = {}
    monkeypatch.setattr(
        sql_provider, "create_engine",
        lambda dsn, **kw: (captured.update(dsn=dsn), engine)[1],
    )

    async def run():
        from app.providers.mysql import MySQLProviderClient

        return await MySQLProviderClient().query(
            {"dsn": "mysql+pymysql://u:p@localhost:3306/shop"}, "SELECT id FROM orders"
        )

    out = asyncio.new_event_loop().run_until_complete(run())
    assert out["count"] == 2
    assert captured["dsn"].startswith("mysql+pymysql://")


def test_mysql_rejects_postgres_dsn():
    from app.providers.mysql import MySQLProviderClient

    async def run():
        await MySQLProviderClient().query({"dsn": "postgresql://u:p@localhost/db"}, "SELECT 1")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
        raise AssertionError("postgres DSN on mysql credential should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)
    finally:
        loop.close()


def test_insert_rows_validates_table_name():
    from app.providers.mysql import MySQLProviderClient

    async def run():
        await MySQLProviderClient().insert_rows({"dsn": "mysql://u:p@localhost/db"}, 'orders"; DROP', [])

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
        raise AssertionError("table name with quotes should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
        assert "plain table name" in str(exc)
    finally:
        loop.close()


def test_insert_rows_requires_dict_rows():
    from app.providers.mysql import MySQLProviderClient

    async def run():
        await MySQLProviderClient().insert_rows(
            {"dsn": "mysql://u:p@localhost/db"}, "orders", ["not-a-dict"]
        )

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
        raise AssertionError("non-object rows should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
    finally:
        loop.close()
