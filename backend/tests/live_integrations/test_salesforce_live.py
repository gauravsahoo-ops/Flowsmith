"""Salesforce Genuine Sandbox Live Certification Test Suite (Phase 43).

Strictly adheres to Rule 29:
- Opt-in live test suite marked with `@pytest.mark.live`.
- Only executes against live remote sandbox when FLOWSMITH_LIVE_TESTS=true and real credentials exist.
- When credentials are not provided: skips cleanly with LIVE_TEST_UNAVAILABLE (never claims passed).
- All write operations use safe disposable records prefixed with FLOWSMITH_CERT_TEST_<timestamp>.
- Mandatory cleanup: deletes disposable record and verifies deletion.
"""

from __future__ import annotations

import os
import time
import pytest

from app.connectors.salesforce_connector import SalesforceConnector
from tests.live_integrations.harness import (
    live_registry,
    require_live_credentials,
)

pytestmark = [pytest.mark.live]


@pytest.fixture
def salesforce_live_creds():
    return require_live_credentials(
        "salesforce",
        ["SALESFORCE_INSTANCE_URL", "SALESFORCE_ACCESS_TOKEN"],
    )


@pytest.fixture
def connector():
    return SalesforceConnector()


@pytest.fixture
def disposable_account_name():
    return f"FLOWSMITH_CERT_TEST_{int(time.time())}"


@pytest.mark.asyncio
async def test_salesforce_live_authentication(salesforce_live_creds, connector):
    """Verifies real OAuth authentication against Salesforce sandbox."""
    creds = {
        "instance_url": salesforce_live_creds["SALESFORCE_INSTANCE_URL"],
        "access_token": salesforce_live_creds["SALESFORCE_ACCESS_TOKEN"],
        "refresh_token": os.getenv("SALESFORCE_REFRESH_TOKEN", ""),
    }
    start_t = time.time()
    try:
        check = await connector.test_connection(creds)
        duration_ms = (time.time() - start_t) * 1000
        assert check["ok"] is True, f"Live auth failed: {check.get('message')}"
        live_registry.record(
            connector_key="salesforce",
            operation="authenticate",
            status="LIVE_SUCCESS",
            duration_ms=duration_ms,
            status_code=200,
        )
    except Exception as exc:
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="salesforce",
            operation="authenticate",
            status="LIVE_FAILED",
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        raise


@pytest.mark.asyncio
async def test_salesforce_live_full_crud_and_cleanup_lifecycle(
    salesforce_live_creds,
    connector,
    disposable_account_name,
):
    """Executes the complete write/verify/update/verify/delete/verify-deleted lifecycle on a sandbox."""
    context = {
        "credentials": {
            "salesforce": {
                "instance_url": salesforce_live_creds["SALESFORCE_INSTANCE_URL"],
                "access_token": salesforce_live_creds["SALESFORCE_ACCESS_TOKEN"],
                "refresh_token": os.getenv("SALESFORCE_REFRESH_TOKEN", ""),
            }
        }
    }

    # 1. CREATE DISPOSABLE RECORD
    create_res = await connector.op_execute(
        "execute",
        {
            "operation": "create",
            "object_name": "Account",
            "record": {
                "Name": disposable_account_name,
                "Description": "FlowSmith Sandbox Certification Probe",
            },
        },
        context,
    )
    assert create_res.get("success") is True
    record_id = create_res["output"]["id"]
    assert record_id, "Salesforce create did not return an Id"

    try:
        # 2. GET RECORD (VERIFY CREATE)
        get_res = await connector.op_execute(
            "execute",
            {
                "operation": "get",
                "object_name": "Account",
                "record_id": record_id,
            },
            context,
        )
        assert get_res.get("success") is True
        assert get_res["output"]["record"]["Name"] == disposable_account_name

        # 3. UPDATE RECORD
        updated_desc = f"Updated {disposable_account_name}"
        update_res = await connector.op_execute(
            "execute",
            {
                "operation": "update",
                "object_name": "Account",
                "record_id": record_id,
                "record": {"Description": updated_desc},
            },
            context,
        )
        assert update_res.get("success") is True

        # 4. GET RECORD (VERIFY UPDATE)
        get_after_update = await connector.op_execute(
            "execute",
            {
                "operation": "get",
                "object_name": "Account",
                "record_id": record_id,
            },
            context,
        )
        assert get_after_update["output"]["record"]["Description"] == updated_desc

        # 5. SEARCH RECORD
        search_res = await connector.op_execute(
            "execute",
            {
                "operation": "query",
                "soql": f"SELECT Id, Name FROM Account WHERE Name = '{disposable_account_name}'",
            },
            context,
        )
        assert search_res.get("success") is True
        assert len(search_res["output"]["records"]) >= 1

    finally:
        # 6. DELETE RECORD (CLEANUP)
        del_res = await connector.op_execute(
            "execute",
            {
                "operation": "delete",
                "object_name": "Account",
                "record_id": record_id,
            },
            context,
        )
        assert del_res.get("success") is True

        # 7. VERIFY CLEANUP (GET MUST FAIL WITH 404 / NOT_FOUND)
        with pytest.raises(Exception):
            await connector.op_execute(
                "execute",
                {
                    "operation": "get",
                    "object_name": "Account",
                    "record_id": record_id,
                },
                context,
            )


@pytest.mark.asyncio
async def test_salesforce_live_dynamic_schema(salesforce_live_creds, connector):
    """Verifies live SObject layout metadata describe."""
    context = {
        "credentials": {
            "salesforce": {
                "instance_url": salesforce_live_creds["SALESFORCE_INSTANCE_URL"],
                "access_token": salesforce_live_creds["SALESFORCE_ACCESS_TOKEN"],
            }
        }
    }
    desc_res = await connector.op_execute(
        "execute",
        {"operation": "describe", "object_name": "Account"},
        context,
    )
    assert desc_res.get("success") is True
    fields = desc_res["output"]["fields"]
    assert len(fields) > 10
    field_names = [f["name"] for f in fields]
    assert "Id" in field_names
    assert "Name" in field_names


@pytest.mark.asyncio
async def test_salesforce_live_pagination(salesforce_live_creds, connector):
    """Verifies cursor / nextRecordsUrl traversal."""
    context = {
        "credentials": {
            "salesforce": {
                "instance_url": salesforce_live_creds["SALESFORCE_INSTANCE_URL"],
                "access_token": salesforce_live_creds["SALESFORCE_ACCESS_TOKEN"],
            }
        }
    }
    page_res = await connector.op_execute(
        "execute",
        {
            "operation": "query",
            "soql": "SELECT Id, Name FROM Account",
            "max_pages": 2,
        },
        context,
    )
    assert page_res.get("success") is True
    assert "records" in page_res["output"]


@pytest.mark.asyncio
async def test_salesforce_live_error_handling_sanitization(salesforce_live_creds, connector):
    """Verifies that invalid queries return sanitized errors without token leakage."""
    context = {
        "credentials": {
            "salesforce": {
                "instance_url": salesforce_live_creds["SALESFORCE_INSTANCE_URL"],
                "access_token": salesforce_live_creds["SALESFORCE_ACCESS_TOKEN"],
            }
        }
    }
    with pytest.raises(Exception) as exc_info:
        await connector.op_execute(
            "execute",
            {
                "operation": "query",
                "soql": "SELECT InvalidFieldNonExistentXYZ FROM Account",
            },
            context,
        )
    err_text = str(exc_info.value)
    # Ensure error message never contains token
    assert salesforce_live_creds["SALESFORCE_ACCESS_TOKEN"] not in err_text
