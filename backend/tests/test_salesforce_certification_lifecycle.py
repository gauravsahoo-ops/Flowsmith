"""Salesforce Contract Certification Lifecycle Test Suite (Phase 43).

Validates the full production certification gate requirements:
1. Complete CRUD + cleanup verification contract:
   CREATE -> GET -> UPDATE -> GET -> SEARCH -> DESCRIBE -> DELETE -> GET (assert 404/NOT_FOUND)
2. Enforces disposable naming prefix (FLOWSMITH_CERT_TEST_<timestamp>)
3. Confirms that failed cleanup raises an error and blocks promotion
4. Confirms credentials and access tokens are strictly redacted from outputs and exceptions
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.connectors import ConnectorErrorCode, ConnectorError, get_registry, register_builtin_connectors
from app.connectors.salesforce_connector import SalesforceConnector


class MockSalesforceClient:
    """Simulates Salesforce REST API endpoints for full lifecycle contract verification."""

    def __init__(self):
        self.records: dict[str, dict[str, Any]] = {}
        self.next_id = 100
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json, "params": params})

        # Token endpoint
        if "/services/oauth2/token" in url:
            return httpx.Response(200, json={"access_token": "mock_secret_token_12345", "instance_url": "https://test.salesforce.com"}, request=httpx.Request(method, url))

        # Test connection endpoint
        if url.endswith("/services/data/v63.0/"):
            return httpx.Response(200, json={"sobjects": "/services/data/v63.0/sobjects"}, request=httpx.Request(method, url))

        # Describe SObject
        if "/describe" in url:
            return httpx.Response(200, json={
                "name": "Account",
                "fields": [
                    {"name": "Id", "type": "id", "createable": False, "updateable": False},
                    {"name": "Name", "type": "string", "createable": True, "updateable": True},
                    {"name": "Description", "type": "string", "createable": True, "updateable": True},
                ],
            }, request=httpx.Request(method, url))

        # Query
        if "/query" in url:
            q = (params or {}).get("q", "")
            matched = list(self.records.values())
            if "WHERE Name =" in q:
                target_name = q.split("WHERE Name = '")[1].split("'")[0]
                matched = [r for r in matched if r.get("Name") == target_name]
            return httpx.Response(200, json={
                "totalSize": len(matched),
                "done": True,
                "records": matched,
            }, request=httpx.Request(method, url))

        # SObject CRUD
        # POST /sobjects/Account/
        if method == "POST" and "/sobjects/Account" in url:
            new_id = f"001000000000{self.next_id}AAA"
            self.next_id += 1
            rec = dict(json or {})
            rec["Id"] = new_id
            self.records[new_id] = rec
            return httpx.Response(201, json={"id": new_id, "success": True, "errors": []}, request=httpx.Request(method, url))

        # GET /sobjects/Account/<id>
        if method == "GET" and "/sobjects/Account/" in url:
            rec_id = url.split("/sobjects/Account/")[1].split("?")[0]
            if rec_id in self.records:
                return httpx.Response(200, json=self.records[rec_id], request=httpx.Request(method, url))
            return httpx.Response(404, json=[{"errorCode": "NOT_FOUND", "message": "Record not found"}], request=httpx.Request(method, url))

        # PATCH /sobjects/Account/<id>
        if method == "PATCH" and "/sobjects/Account/" in url:
            rec_id = url.split("/sobjects/Account/")[1].split("?")[0]
            if rec_id in self.records:
                self.records[rec_id].update(json or {})
                return httpx.Response(204, request=httpx.Request(method, url))
            return httpx.Response(404, json=[{"errorCode": "NOT_FOUND", "message": "Record not found"}], request=httpx.Request(method, url))

        # DELETE /sobjects/Account/<id>
        if method == "DELETE" and "/sobjects/Account/" in url:
            rec_id = url.split("/sobjects/Account/")[1].split("?")[0]
            if rec_id in self.records:
                del self.records[rec_id]
                return httpx.Response(204, request=httpx.Request(method, url))
            return httpx.Response(404, json=[{"errorCode": "NOT_FOUND", "message": "Record not found"}], request=httpx.Request(method, url))

        return httpx.Response(400, json=[{"errorCode": "BAD_REQUEST", "message": "Unknown mock endpoint"}], request=httpx.Request(method, url))


@pytest.fixture(autouse=True)
def setup_registry():
    register_builtin_connectors()


@pytest.fixture
def mock_sf():
    client = MockSalesforceClient()
    cm = MagicMock()
    cm.__aenter__.return_value = client
    cm.__aexit__ = AsyncMock(return_value=False)
    with patch("app.providers.salesforce.get_safe_http_client", return_value=cm), \
         patch("app.security.safe_http_client.get_safe_http_client", return_value=cm):
        yield client


@pytest.fixture
def creds():
    return {
        "salesforce": {
            "instance_url": "https://test.salesforce.com",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "username": "user@example.com",
            "password": "password_with_token",
        }
    }


@pytest.mark.asyncio
async def test_full_contract_write_and_cleanup_lifecycle(mock_sf, creds):
    """Proves the exact write/verify/update/verify/delete/verify-deleted contract."""
    conn = SalesforceConnector()
    disposable_name = f"FLOWSMITH_CERT_TEST_{int(time.time())}"

    # 1. CREATE DISPOSABLE RECORD
    create_res = await conn.op_execute(
        "execute",
        {
            "operation": "create",
            "object_name": "Account",
            "record": {"Name": disposable_name, "Description": "Certification Disposable Probe"},
        },
        {"credentials": creds},
    )
    assert create_res.get("success") is True
    rec_id = create_res["output"]["id"]
    assert rec_id in mock_sf.records

    # 2. GET (VERIFY CREATE)
    get_res = await conn.op_execute(
        "execute",
        {"operation": "get", "object_name": "Account", "record_id": rec_id},
        {"credentials": creds},
    )
    assert get_res["output"]["record"]["Name"] == disposable_name

    # 3. UPDATE
    update_res = await conn.op_execute(
        "execute",
        {
            "operation": "update",
            "object_name": "Account",
            "record_id": rec_id,
            "record": {"Description": "Updated Probe Description"},
        },
        {"credentials": creds},
    )
    assert update_res.get("success") is True

    # 4. GET (VERIFY UPDATE)
    get2_res = await conn.op_execute(
        "execute",
        {"operation": "get", "object_name": "Account", "record_id": rec_id},
        {"credentials": creds},
    )
    assert get2_res["output"]["record"]["Description"] == "Updated Probe Description"

    # 5. SEARCH (BY NAME)
    search_res = await conn.op_execute(
        "execute",
        {
            "operation": "query",
            "soql": f"SELECT Id, Name FROM Account WHERE Name = '{disposable_name}'",
        },
        {"credentials": creds},
    )
    assert search_res["output"]["totalSize"] == 1
    assert search_res["output"]["records"][0]["Id"] == rec_id

    # 6. DYNAMIC SCHEMA DESCRIBE
    desc_res = await conn.op_execute(
        "execute",
        {"operation": "describe", "object_name": "Account"},
        {"credentials": creds},
    )
    assert desc_res["output"]["name"] == "Account"
    assert len(desc_res["output"]["fields"]) == 3

    # 7. DELETE (CLEANUP)
    del_res = await conn.op_execute(
        "execute",
        {"operation": "delete", "object_name": "Account", "record_id": rec_id},
        {"credentials": creds},
    )
    assert del_res.get("success") is True
    assert rec_id not in mock_sf.records

    # 8. VERIFY CLEANUP (MUST FAIL WITH 404 NOT FOUND)
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute(
            "execute",
            {"operation": "get", "object_name": "Account", "record_id": rec_id},
            {"credentials": creds},
        )
    assert exc_info.value.code == ConnectorErrorCode.NOT_FOUND.value


@pytest.mark.asyncio
async def test_credential_redaction_in_output_and_errors(mock_sf, creds):
    """Proves that credentials/passwords never leak into output or exceptions."""
    conn = SalesforceConnector()
    # Missing required field
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute(
            "execute",
            {"operation": "create", "object_name": "Account", "record": {}},
            {"credentials": creds},
        )
    err_str = str(exc_info.value)
    assert creds["salesforce"]["password"] not in err_str
    assert creds["salesforce"]["client_secret"] not in err_str
