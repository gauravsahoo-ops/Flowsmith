"""MongoDB provider client (Phase 11 business connectors).

PyMongo (synchronous) executed via ``asyncio.to_thread`` — one client
per call, mirroring the Database Query node's engine-per-call pattern.

The ``pymongo`` package is an optional dependency: when missing, every
operation fails with a typed NOT_CONFIGURED error telling the operator
exactly what to install.
"""

from __future__ import annotations

import asyncio
from typing import Any

from typing_extensions import NoReturn

from app.connectors import ConnectorErrorCode, make_connector_error

_MAX_DOCS = 500


def _require_pymongo():
    try:
        import pymongo  # noqa: PLC0415 - optional dependency
        from pymongo.errors import PyMongoError
    except ImportError as exc:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "MongoDB support needs the 'pymongo' package (pip install pymongo).",
            retryable=False,
        ) from exc
    return pymongo, PyMongoError


def _require_uri(creds: dict) -> str:
    uri = str((creds or {}).get("uri") or "").strip()
    if not uri:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "MongoDB connector needs a 'mongodb' credential with a connection URI "
            "(mongodb:// or mongodb+srv://).",
            retryable=False,
        )
    lowered = uri.lower()
    if not (lowered.startswith("mongodb://") or lowered.startswith("mongodb+srv://")):
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "A MongoDB credential URI must start with mongodb:// or mongodb+srv://.",
            retryable=False,
        )
    return uri


def _namespace(database: str, collection: str) -> tuple[str, str]:
    db = str(database or "").strip()
    coll = str(collection or "").strip()
    if not db or not coll:
        raise make_connector_error(
            ConnectorErrorCode.BAD_REQUEST, "database and collection are required.", retryable=False,
        )
    for name in (db, coll):
        if any(ch in name for ch in ('"', "$", "\x00")) or name in ("admin", "local", "config"):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"Invalid namespace component '{name}'.", retryable=False,
            )
    return db, coll


def _sanitize(doc: Any) -> Any:
    """Make documents JSON-safe: ObjectId -> str."""
    from bson import ObjectId  # part of pymongo

    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, dict):
        return {k: _sanitize(v) for k, v in doc.items()}
    if isinstance(doc, (list, tuple)):
        return [_sanitize(v) for v in doc]
    return doc


def _translate(exc: Exception, product_op: str) -> NoReturn:
    raise make_connector_error(
        ConnectorErrorCode.UNAVAILABLE if _looks_transient(exc) else ConnectorErrorCode.BAD_REQUEST,
        f"MongoDB {product_op} failed: {exc}",
        retryable=_looks_transient(exc),
    )


_TRANSIENT_MARKERS = ("connection", "timeout", "timed out", "pool", "auth", "not found")


def _looks_transient(exc: Exception) -> bool:
    message = str(exc).lower()
    # Auth failures are permanent; everything connection-ish is transient.
    if "authentication" in message or "auth failed" in message:
        return False
    return any(marker in message for marker in _TRANSIENT_MARKERS)


class MongoProviderClient:
    """Low-level MongoDB operations (find/insert/update/delete)."""

    async def find(self, creds: dict, database: str, collection: str,
                   filter_query: dict | None = None, limit: int = 50,
                   skip: int = 0, timeout: float = 30.0) -> dict:
        db, coll = _namespace(database, collection)
        limit = min(max(int(limit or 50), 1), _MAX_DOCS)
        skip = max(int(skip or 0), 0)

        def job() -> dict[str, Any]:
            pymongo, PyMongoError = _require_pymongo()
            try:
                client = pymongo.MongoClient(_require_uri(creds), serverSelectionTimeoutMS=int(timeout * 1000))
                try:
                    cursor = client[db][coll].find(filter_query or {}).skip(skip).limit(limit)
                    docs = [_sanitize(d) for d in cursor]
                    return {"documents": docs, "count": len(docs)}
                finally:
                    client.close()
            except PyMongoError as exc:
                _translate(exc, "find")

        return await asyncio.to_thread(job)

    async def insert_one(self, creds: dict, database: str, collection: str,
                         document: dict, timeout: float = 30.0) -> dict:
        db, coll = _namespace(database, collection)
        if not isinstance(document, dict) or not document:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "insert requires a document object.", retryable=False)

        def job() -> dict[str, Any]:
            pymongo, PyMongoError = _require_pymongo()
            try:
                client = pymongo.MongoClient(_require_uri(creds), serverSelectionTimeoutMS=int(timeout * 1000))
                try:
                    result = client[db][coll].insert_one(document)
                    return {"inserted_id": str(result.inserted_id), "success": True}
                finally:
                    client.close()
            except PyMongoError as exc:
                _translate(exc, "insert")

        return await asyncio.to_thread(job)

    async def update_one(self, creds: dict, database: str, collection: str,
                         filter_query: dict, update: dict, timeout: float = 30.0) -> dict:
        db, coll = _namespace(database, collection)
        if not isinstance(filter_query, dict) or not filter_query:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update requires a filter object.", retryable=False)
        if not isinstance(update, dict) or not update:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "update requires an update expression (e.g. {'$set': {...}}).", retryable=False)
        first_key = next(iter(update))
        if not first_key.startswith("$"):
            update = {"$set": update}

        def job() -> dict[str, Any]:
            pymongo, PyMongoError = _require_pymongo()
            try:
                client = pymongo.MongoClient(_require_uri(creds), serverSelectionTimeoutMS=int(timeout * 1000))
                try:
                    result = client[db][coll].update_one(filter_query, update)
                    return {"matched": result.matched_count, "modified": result.modified_count}
                finally:
                    client.close()
            except PyMongoError as exc:
                _translate(exc, "update")

        return await asyncio.to_thread(job)

    async def delete_one(self, creds: dict, database: str, collection: str,
                         filter_query: dict, timeout: float = 30.0) -> dict:
        db, coll = _namespace(database, collection)
        if not isinstance(filter_query, dict) or not filter_query:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "delete requires a filter object.", retryable=False)

        def job() -> dict[str, Any]:
            pymongo, PyMongoError = _require_pymongo()
            try:
                client = pymongo.MongoClient(_require_uri(creds), serverSelectionTimeoutMS=int(timeout * 1000))
                try:
                    result = client[db][coll].delete_one(filter_query)
                    return {"deleted": result.deleted_count}
                finally:
                    client.close()
            except PyMongoError as exc:
                _translate(exc, "delete")

        return await asyncio.to_thread(job)
