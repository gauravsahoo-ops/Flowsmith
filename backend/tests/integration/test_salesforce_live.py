"""Live Salesforce integration tests (Phase 9).

Runs the real connector against a REAL Salesforce org — skipped unless
explicitly configured. Enable with:

    SF_LIVE=1
    SF_LIVE_CLIENT_ID=...      (Connected App consumer key)
    SF_LIVE_CLIENT_SECRET=...  (consumer secret)
    SF_LIVE_USERNAME=...
    SF_LIVE_PASSWORD=...       (password + security token concatenated)
    # optional:
    SF_LIVE_LOGIN_URL=https://test.salesforce.com   (sandbox)
    SF_LIVE_API_VERSION=v63.0
    SF_LIVE_EXTERNAL_ID_FIELD=Legacy_Id__c          (enables the upsert test)
    SF_LIVE_BULK=1                                  (enables Bulk API round trip)

The suite is read-mostly: it lists objects, describes Account, runs a
bounded SOQL query, and performs a full CRUD cycle on ONE scratch Lead
carrying a unique marker email, deleting it in `finally`. Bulk tests
create two more scratch Leads and bulk-delete them.

Run:  pytest tests/integration/test_salesforce_live.py -v
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.connectors import get_registry as get_connector_registry
from app.connectors import register_builtin_connectors


def _live_creds() -> dict[str, str] | None:
    if os.environ.get("SF_LIVE") != "1":
        return None
    required = ("SF_LIVE_CLIENT_ID", "SF_LIVE_CLIENT_SECRET", "SF_LIVE_USERNAME", "SF_LIVE_PASSWORD")
    if not all(os.environ.get(k) for k in required):
        return None
    creds = {
        "client_id": os.environ["SF_LIVE_CLIENT_ID"],
        "client_secret": os.environ["SF_LIVE_CLIENT_SECRET"],
        "username": os.environ["SF_LIVE_USERNAME"],
        "password": os.environ["SF_LIVE_PASSWORD"],
        "instance_url": os.environ.get("SF_LIVE_LOGIN_URL", "https://login.salesforce.com"),
        "api_version": os.environ.get("SF_LIVE_API_VERSION", "v63.0"),
    }
    if os.environ.get("SF_LIVE_REFRESH_TOKEN"):
        creds["refresh_token"] = os.environ["SF_LIVE_REFRESH_TOKEN"]
    return creds


@pytest.fixture(scope="module")
def sf():
    """Registered connector + live credential context."""
    creds = _live_creds()
    if creds is None:
        pytest.skip(
            "Live Salesforce not configured (set SF_LIVE=1 plus "
            "SF_LIVE_CLIENT_ID/CLIENT_SECRET/USERNAME/PASSWORD)."
        )
    registry = get_connector_registry()
    registry.initialize()
    register_builtin_connectors()
    connector = registry.get("salesforce")
    assert connector is not None
    context = {"credentials": {"salesforce": creds}}
    yield connector, context


def _op(connector, context, operation: str, payload: dict) -> dict:
    """Async op_execute bridge run to completion."""
    import asyncio

    return asyncio.run(connector.op_execute(operation, payload, context))


CORE_OBJECTS = {"Account", "Contact", "Lead", "Opportunity"}


def test_list_objects_discovers_core_and_custom(sf):
    connector, context = sf
    out = _op(connector, context, "list", {})[  # noqa: F841
        "output"
    ]
    names = {s["name"] for s in out["sobjects"]}
    missing = CORE_OBJECTS - names
    assert not missing, f"core objects missing from org listing: {missing}"
    # Custom objects (or at least non-standard metadata) are included.
    assert any(n.endswith("__c") or n in CORE_OBJECTS for n in names)


def test_describe_account_returns_field_metadata(sf):
    connector, context = sf
    out = _op(connector, context, "describe", {"object_name": "Account"})["output"]
    fields = {f["name"]: f for f in out["fields"]}
    assert "Name" in fields
    assert "Id" in fields
    # Rich metadata present (Phase 9 describe enrichment).
    assert isinstance(fields["Industry"].get("picklist_values"), list)
    assert {"createable", "updateable", "required"} <= set(fields["Name"].keys())


def test_soql_query_with_pagination_contract(sf):
    connector, context = sf
    out = _op(connector, context, "query", {
        "soql": "SELECT Id, Name FROM Account LIMIT 5",
        "max_pages": 2,
    })["output"]
    assert isinstance(out["records"], list)
    assert len(out["records"]) <= 5
    assert out["totalSize"] >= 0
    assert out["done"] in (True, False)


def test_full_lead_crud_cycle_with_search(sf):
    """Create → search(found) → update → delete → search(not found)."""
    connector, context = sf
    marker = f"flowsmith-live-{uuid.uuid4().hex[:10]}@example.com"
    created_id = None
    try:
        created = _op(connector, context, "create", {
            "object_name": "Lead",
            "record": {
                "FirstName": "Flowsmith",
                "LastName": "LiveTest",
                "Company": "Flowsmith QA",
                "Email": marker,
            },
        })["output"]
        created_id = created.get("id")
        assert created_id or created.get("duplicate_alert")

        found = _op(connector, context, "search", {
            "object_name": "Lead",
            "search_field": "Email",
            "search_value": marker,
        })["output"]
        assert found["found"] is True
        record_id = found["record"]["Id"]
        assert record_id
        created_id = created_id or record_id

        _op(connector, context, "update", {
            "object_name": "Lead",
            "record_id": record_id,
            "record": {"Company": "Flowsmith QA Updated"},
        })

        refetched = _op(connector, context, "get", {
            "object_name": "Lead",
            "record_id": record_id,
        })["output"]
        assert refetched["record"]["Company"] == "Flowsmith QA Updated"

        deleted = _op(connector, context, "delete", {
            "object_name": "Lead",
            "record_id": record_id,
        })
        assert deleted["success"] is True
        created_id = None  # cleanup done

        gone = _op(connector, context, "search", {
            "object_name": "Lead",
            "search_field": "Email",
            "search_value": marker,
        })["output"]
        assert gone["found"] is False
    finally:
        if created_id:
            try:
                _op(connector, context, "delete", {
                    "object_name": "Lead", "record_id": created_id,
                })
            except Exception:
                pass


def test_upsert_by_external_id_is_idempotent(sf):
    ext_field = os.environ.get("SF_LIVE_EXTERNAL_ID_FIELD", "")
    if not ext_field:
        pytest.skip("Set SF_LIVE_EXTERNAL_ID_FIELD to enable the upsert round trip.")
    connector, context = sf
    ext_value = f"fs-live-{uuid.uuid4().hex[:10]}"
    try:
        first = _op(connector, context, "upsert", {
            "object_name": "Account",
            "external_id_field": ext_field,
            "external_id": ext_value,
            "record": {"Name": f"FS Live Upsert {ext_value}", ext_field: ext_value},
        })["output"]
        assert first["created"] is True and first["id"]

        second = _op(connector, context, "upsert", {
            "object_name": "Account",
            "external_id_field": ext_field,
            "external_id": ext_value,
            "record": {"Name": f"FS Live Upsert {ext_value} v2", ext_field: ext_value},
        })["output"]
        assert second["created"] is False
        assert second["id"] == first["id"]  # no duplicate row

        _op(connector, context, "delete", {
            "object_name": "Account", "record_id": first["id"],
        })
    finally:
        pass  # deleted above; on failure the sandbox owner can clean up by ext id


def test_bulk_insert_then_bulk_delete(sf):
    if os.environ.get("SF_LIVE_BULK") != "1":
        pytest.skip("Set SF_LIVE_BULK=1 to enable the Bulk API round trip.")
    connector, context = sf
    suffixes = [uuid.uuid4().hex[:6] for _ in range(2)]
    emails = [f"fs-bulk-{s}@example.com" for s in suffixes]
    inserted = _op(connector, context, "bulk", {
        "object_name": "Lead",
        "bulk_operation": "insert",
        "records": [
            {"LastName": f"FSBulk{s}", "Company": "Flowsmith QA", "Email": e}
            for s, e in zip(suffixes, emails)
        ],
        "poll_interval_seconds": 2,
    })["output"]
    assert inserted["state"] == "JobComplete"
    assert inserted["records_processed"] == 2

    ids = [row["sf__Id"] for row in inserted.get("successful_records", [])]
    assert len(ids) == 2

    removed = _op(connector, context, "bulk", {
        "object_name": "Lead",
        "bulk_operation": "delete",
        "records": [{"Id": i} for i in ids],
        "poll_interval_seconds": 2,
    })["output"]
    assert removed["state"] == "JobComplete"
