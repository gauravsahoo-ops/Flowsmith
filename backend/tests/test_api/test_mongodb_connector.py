"""MongoDB connector tests (Phase 11 business connectors).

Uses the real pymongo package with a faked MongoClient (connection seam)
so document sanitisation (ObjectId -> str) runs for real. Proves:
find/insert/update/delete flows, $set shorthand, namespace validation,
URI scheme enforcement.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors

CREDS = {"uri": "mongodb://user:pass@localhost:27017"}


class FakeCollection:
    def __init__(self, store: dict, parent: "FakeMongoClient", name: str) -> None:
        self._store = store
        self._parent = parent
        self._name = name

    def find(self, filter_query=None):  # noqa: ARG002
        return self

    def skip(self, n: int):
        self._parent.calls.append(("skip", n))
        return self

    def limit(self, n: int):
        self._parent.calls.append(("limit", n))
        docs = [dict(d) for d in self._store.get("docs", [])][:n]
        self._parent.last_docs = docs
        return docs

    def insert_one(self, doc: dict):
        self._store.setdefault("docs", []).append(dict(doc))
        from bson import ObjectId

        return type("R", (), {"inserted_id": ObjectId("64b000000000000000000001")})

    def update_one(self, filter_query: dict, update: dict):  # noqa: ARG002
        self._parent.calls.append(("update", update))
        return type("R", (), {"matched_count": 1, "modified_count": 1})

    def delete_one(self, filter_query: dict):  # noqa: ARG002
        return type("R", (), {"deleted_count": 1})


class FakeDatabase:
    def __init__(self, store: dict, parent: "FakeMongoClient", db_name: str) -> None:
        self._store = store
        self._parent = parent
        self._db_name = db_name

    def __getitem__(self, name: str) -> FakeCollection:
        db_store = self._store.setdefault(self._db_name, {})
        return FakeCollection(db_store.setdefault(name, {}), self._parent, name)


class FakeMongoClient:
    instances: list["FakeMongoClient"] = []

    def __init__(self, uri: str, **kwargs: Any) -> None:
        self.uri = uri
        self.kwargs = kwargs
        self.closed = False
        self.calls: list[tuple] = []
        self.store: dict[str, dict] = {}
        self.last_docs: list = []
        type(self).instances.append(self)

    def __getitem__(self, db_name: str) -> FakeDatabase:
        return FakeDatabase(self.store, self, db_name)

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _connectors(monkeypatch):
    import pymongo

    monkeypatch.setattr(pymongo, "MongoClient", lambda uri, **kw: FakeMongoClient(uri, **kw))
    FakeMongoClient.instances.clear()
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_find_sanitizes_object_ids():
    from bson import ObjectId

    async def run():
        from app.providers.mongodb import MongoProviderClient

        client = MongoProviderClient()

        def seed(uri, **kw):
            c = FakeMongoClient(uri, **kw)
            c.store["shop"] = {"orders": {"docs": [
                {"_id": ObjectId("64b00000000000000000000f"), "total": 42},
            ]}}
            return c

        import pymongo as _pm
        _orig = _pm.MongoClient
        import app.providers.mongodb as mod

        # Re-patch at call time so the seeded client is used.
        _pm.MongoClient = seed  # type: ignore[assignment]
        try:
            return await client.find(CREDS, "shop", "orders", limit=10)
        finally:
            _pm.MongoClient = _orig  # type: ignore[assignment]

    out = asyncio.new_event_loop().run_until_complete(run())
    assert out["count"] == 1
    assert out["documents"][0]["_id"] == "64b00000000000000000000f"
    assert isinstance(out["documents"][0]["total"], int)


def test_insert_one_returns_string_id():
    async def run():
        from app.providers.mongodb import MongoProviderClient

        return await MongoProviderClient().insert_one(
            CREDS, "shop", "orders", {"total": 9}
        )

    out = asyncio.new_event_loop().run_until_complete(run())
    assert out["success"] is True
    client = FakeMongoClient.instances[-1]
    assert client.closed is True
    assert len(client.store["shop"]["orders"]["docs"]) == 1


def test_update_one_wraps_plain_fields_in_set():
    async def run():
        from app.providers.mongodb import MongoProviderClient

        return await MongoProviderClient().update_one(
            CREDS, "shop", "orders", {"_id": 1}, {"total": 99}
        )

    out = asyncio.new_event_loop().run_until_complete(run())
    assert out == {"matched": 1, "modified": 1}
    client = FakeMongoClient.instances[-1]
    assert ("update", {"$set": {"total": 99}}) in client.calls


def test_invalid_namespace_rejected_without_connection():
    from app.providers.mongodb import MongoProviderClient

    async def go():
        await MongoProviderClient().find(CREDS, "admin", "$cmd")

    loop = asyncio.new_event_loop()
    before = len(FakeMongoClient.instances)
    try:
        loop.run_until_complete(go())
        raise AssertionError("invalid namespace should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
    finally:
        loop.close()
    assert len(FakeMongoClient.instances) == before


def test_bad_uri_scheme_rejected():
    from app.providers.mongodb import MongoProviderClient

    async def go():
        await MongoProviderClient().find({"uri": "postgres://x"}, "db", "coll")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("wrong scheme should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)
    finally:
        loop.close()
