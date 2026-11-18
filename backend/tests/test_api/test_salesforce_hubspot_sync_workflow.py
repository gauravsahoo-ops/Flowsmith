"""End-to-end Salesforce -> HubSpot sync workflow.

The workflow under test is the shipped example in ``docs/examples``:

* ``salesforce_to_hubspot_contact_sync.json`` (batch parent)
* ``salesforce_hubspot_contact_upsert.json`` (per-contact child)

Salesforce and HubSpot HTTP calls are routed by a stateful fake that behaves
like a small CRM: searches, creates, updates, and associations mutate state,
so the second run proves the workflow is idempotent (updates, not duplicates).
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import httpx
import pytest

from app.connectors import get_registry, register_builtin_connectors
from tests.test_api.conftest import auth_headers, register

pytestmark = pytest.mark.timing

EXAMPLES = Path(__file__).resolve().parents[3] / "docs" / "examples"
PARENT_ID = "wf_salesforce_to_hubspot_contact_sync"
CHILD_ID = "wf_salesforce_hubspot_contact_upsert"
SF_PLACEHOLDER = "REPLACE_WITH_SALESFORCE_CREDENTIAL_ID"
HS_PLACEHOLDER = "REPLACE_WITH_HUBSPOT_CREDENTIAL_ID"

SF_DATA = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "cid_sf_hubspot_sync",
    "client_secret": "sf-secret",
    "username": "sync@example.com",
    "password": "sf-password-token",
    "api_version": "v63.0",
}
HS_DATA = {"private_token": "PAT_SF_HUBSPOT_SYNC"}

ACME_CONTACT = {
    "Id": "003ACME000000001",
    "FirstName": "Ada",
    "LastName": "Lovelace",
    "Name": "Ada Lovelace",
    "Email": "ADA@ACME.COM",
    "Title": "VP Engineering",
    "Phone": "+1 415 555 0100",
    "Department": "Engineering",
    "LeadSource": "Web",
    "AccountId": "001ACME000000001",
    "Account": {
        "Id": "001ACME000000001",
        "Name": "Acme Corporation",
        "Website": "https://www.acme.com/about?ref=sf",
        "Industry": "Technology",
        "BillingCountry": "USA",
        "BillingCity": "San Francisco",
        "AnnualRevenue": 5_000_000,
        "NumberOfEmployees": 800,
        "Type": "Customer",
        "Owner": {"Name": "Grace Hopper", "Email": "grace@acme.com"},
    },
}

GLOBEX_CONTACT = {
    "Id": "003GLOBEX00000002",
    "FirstName": "Bob",
    "LastName": "Stone",
    "Name": "Bob Stone",
    "Email": "bob@globex.io",
    "Title": "CTO",
    "Phone": "+1 212 555 0199",
    "LeadSource": "Partner",
    "AccountId": "001GLOBEX00000002",
    "Account": {
        "Id": "001GLOBEX00000002",
        "Name": "Globex",
        "Website": "http://globex.io",
        "Industry": "Manufacturing",
        "BillingCountry": "Canada",
        "BillingCity": "Toronto",
        "AnnualRevenue": 1_200_000,
        "NumberOfEmployees": 120,
        "Type": "Prospect",
        "Owner": {"Name": "Hank Scorpio", "Email": "hank@globex.io"},
    },
}

UMBRELLA_CONTACT = {
    "Id": "003UMBRELLA000003",
    "FirstName": "Wendy",
    "LastName": "Lee",
    "Name": "Wendy Lee",
    "Email": "wendy@umbrella.example",
    "Title": "Office Manager",
    "LeadSource": "Other",
    "AccountId": "001UMBRELLA000003",
    "Account": {
        "Id": "001UMBRELLA000003",
        "Name": "Umbrella",
        "Website": "https://umbrella.example",
        "Industry": "Retail",
        "BillingCountry": "Germany",
        "BillingCity": "Berlin",
        "AnnualRevenue": 50_000,
        "NumberOfEmployees": 25,
        "Type": "Prospect",
    },
}

INITECH_CONTACT = {
    "Id": "003INITECH0000004",
    "FirstName": "Peter",
    "LastName": "Gibbons",
    "Name": "Peter Gibbons",
    "Email": "peter@initech.com",
    "Title": "Engineer",
    "LeadSource": "Web",
    "AccountId": "001INITECH0000004",
    "Account": {
        "Id": "001INITECH0000004",
        "Name": "Initech",
        "Website": "",
        "Industry": "Technology",
        "BillingCountry": "USA",
        "AnnualRevenue": 900_000,
        "NumberOfEmployees": 80,
        "Type": "Prospect",
    },
}

FAILCO_CONTACT = {
    "Id": "003FAILCO00000005",
    "FirstName": "Milton",
    "LastName": "Waddams",
    "Name": "Milton Waddams",
    "Email": "milton@failco.example",
    "Title": "Collator",
    "AccountId": "001FAILCO00000005",
    "Account": {
        "Id": "001FAILCO00000005",
        "Name": "FailCo",
        "Website": "https://failco.example",
        "Industry": "Technology",
        "BillingCountry": "USA",
        "AnnualRevenue": 800_000,
        "NumberOfEmployees": 60,
        "Type": "Prospect",
    },
}

ACME_DEAL_NAME = f"Flowsmith Sync | Acme Corporation | {ACME_CONTACT['Id']}"
GLOBEX_DEAL_NAME = f"Flowsmith Sync | Globex | {GLOBEX_CONTACT['Id']}"


def _response(status: int, payload: Any | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("GET", "http://fake-router"),
    )


def _empty(status: int = 204) -> httpx.Response:
    return httpx.Response(
        status,
        content=b"",
        request=httpx.Request("PUT", "http://fake-router"),
    )


class RoutedVendorFake:
    """Stateful Salesforce/HubSpot fake routed by method + URL."""

    def __init__(
        self,
        sf_records: list[dict[str, Any]],
        *,
        companies: list[dict[str, Any]] | None = None,
        contacts: list[dict[str, Any]] | None = None,
        deals: list[dict[str, Any]] | None = None,
        fail_company_create_domains: set[str] | None = None,
    ) -> None:
        self.sf_records = sf_records
        self.companies = {row["id"]: row for row in (companies or [])}
        self.contacts = {row["id"]: row for row in (contacts or [])}
        self.deals = {row["id"]: row for row in (deals or [])}
        self.associations: list[tuple[str, str, str, str, str]] = []
        self.fail_company_create_domains = set(fail_company_create_domains or ())
        self.calls: list[dict[str, Any]] = []
        self._next_id = 1

    # -- helpers -------------------------------------------------------
    def _new_id(self, prefix: str) -> str:
        value = f"{prefix}_{self._next_id:04d}"
        self._next_id += 1
        return value

    @staticmethod
    def _search(store: dict[str, dict[str, Any]], field: str, value: str) -> list[dict[str, Any]]:
        return [
            row
            for row in store.values()
            if str((row.get("properties") or {}).get(field) or "") == value
        ]

    def company_by_domain(self, domain: str) -> dict[str, Any] | None:
        matches = self._search(self.companies, "domain", domain)
        return matches[0] if matches else None

    def contact_by_email(self, email: str) -> dict[str, Any] | None:
        matches = self._search(self.contacts, "email", email)
        return matches[0] if matches else None

    def deal_by_name(self, name: str) -> dict[str, Any] | None:
        matches = self._search(self.deals, "dealname", name)
        return matches[0] if matches else None

    def calls_for(self, method: str, path_contains: str) -> list[dict[str, Any]]:
        return [
            call
            for call in self.calls
            if call["method"] == method and path_contains in call["path"]
        ]

    # -- httpx client surface -----------------------------------------
    async def __aenter__(self) -> "RoutedVendorFake":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        parsed = urlparse(url)
        path = parsed.path
        call = {
            "method": method.upper(),
            "url": url,
            "path": path,
            "json": kwargs.get("json"),
            "params": kwargs.get("params"),
            "data": kwargs.get("data"),
        }
        self.calls.append(call)

        if "salesforce.com" in parsed.netloc:
            return self._salesforce(call)
        if parsed.netloc == "api.hubapi.com":
            return self._hubspot(call)
        return _response(404, {"message": f"unexpected host {parsed.netloc}"})

    # -- Salesforce ----------------------------------------------------
    def _salesforce(self, call: dict[str, Any]) -> httpx.Response:
        if call["path"].endswith("/services/oauth2/token"):
            return _response(
                200,
                {
                    "access_token": "sf-access-token",
                    "instance_url": "https://myorg.salesforce.com",
                },
            )
        if "/services/data/" in call["path"] and call["path"].endswith("/query"):
            query = str((call["params"] or {}).get("q") or "")
            if "FROM Contact" not in query:
                return _response(400, [{"message": "unexpected SOQL", "errorCode": "MALFORMED_QUERY"}])
            return _response(
                200,
                {
                    "records": self.sf_records,
                    "totalSize": len(self.sf_records),
                    "done": True,
                    "nextRecordsUrl": None,
                },
            )
        return _response(404, [{"message": f"unexpected Salesforce path {call['path']}"}])

    # -- HubSpot -------------------------------------------------------
    def _hubspot(self, call: dict[str, Any]) -> httpx.Response:
        path = call["path"]
        parts = [part for part in path.split("/") if part]
        # crm/v3/objects/{object_type}[/...]
        if len(parts) < 4 or parts[:3] != ["crm", "v3", "objects"]:
            return _response(404, {"message": f"unexpected HubSpot path {path}"})
        object_type = parts[3]

        if object_type not in ("companies", "contacts", "deals"):
            return _response(404, {"message": f"unsupported object {object_type}"})

        store = getattr(self, object_type)

        if len(parts) == 5 and parts[4] == "search" and call["method"] == "POST":
            body = call["json"] or {}
            filters = ((body.get("filterGroups") or [{}])[0].get("filters") or [{}])[0]
            field = str(filters.get("propertyName") or "")
            value = str(filters.get("value") or "")
            matches = self._search(store, field, value)
            return _response(200, {"results": matches, "total": len(matches)})

        if len(parts) == 4 and call["method"] == "POST":
            properties = dict((call["json"] or {}).get("properties") or {})
            domain = str(properties.get("domain") or "")
            if object_type == "companies" and domain in self.fail_company_create_domains:
                return _response(
                    400,
                    {
                        "category": "VALIDATION_ERROR",
                        "message": f"forced company create failure for {domain}",
                    },
                )
            record_id = self._new_id(
                {"companies": "c", "contacts": "ct", "deals": "d"}[object_type]
            )
            row = {"id": record_id, "properties": properties}
            store[record_id] = row
            return _response(201, row)

        if len(parts) == 5 and call["method"] == "PATCH":
            record_id = parts[4]
            row = store.get(record_id)
            if row is None:
                return _response(404, {"message": f"{object_type} {record_id} not found"})
            properties = dict(row.get("properties") or {})
            properties.update((call["json"] or {}).get("properties") or {})
            row["properties"] = properties
            return _response(200, row)

        if len(parts) == 9 and parts[5] == "associations" and call["method"] == "PUT":
            # /crm/v3/objects/{from}/{id}/associations/{to}/{id}/{type}
            from_id = parts[4]
            to_object = parts[6]
            to_id = parts[7]
            association_type = parts[8]
            self.associations.append(
                (object_type, from_id, to_object, to_id, association_type)
            )
            return _empty(204)

        return _response(
            404,
            {"message": f"unhandled HubSpot call {call['method']} {path}"},
        )


@contextmanager
def route_vendor_http(router: RoutedVendorFake):
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=router)
    context_manager.__aexit__ = AsyncMock(return_value=False)
    patchers = [
        patch("app.providers.salesforce.get_safe_http_client", return_value=context_manager),
        patch("app.providers.hubspot.get_safe_http_client", return_value=context_manager),
    ]
    for patcher in patchers:
        patcher.start()
    try:
        yield router
    finally:
        for patcher in reversed(patchers):
            patcher.stop()


@pytest.fixture(autouse=True)
def _connectors_registered():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    yield


def _setup(client):
    return auth_headers(register(client)["token"])


def _create_credential(client, headers, cred_type: str, data: dict, name: str) -> str:
    resp = client.post(
        "/api/credentials",
        json={"name": name, "type": cred_type, "data": data},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


def _replace_placeholders(value: Any, sf_cred: str, hs_cred: str) -> Any:
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, sf_cred, hs_cred) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_placeholders(item, sf_cred, hs_cred) for item in value]
    if value == SF_PLACEHOLDER:
        return sf_cred
    if value == HS_PLACEHOLDER:
        return hs_cred
    return value


def _load_example(name: str, sf_cred: str, hs_cred: str) -> dict[str, Any]:
    raw = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    return _replace_placeholders(raw, sf_cred, hs_cred)


def _import_workflows(client, headers, sf_cred: str, hs_cred: str) -> None:
    child = _load_example("salesforce_hubspot_contact_upsert.json", sf_cred, hs_cred)
    parent = _load_example("salesforce_to_hubspot_contact_sync.json", sf_cred, hs_cred)
    for workflow in (child, parent):
        resp = client.post("/api/workflows", json=workflow, headers=headers)
        assert resp.status_code in (200, 201), resp.text


def _run_and_poll(client, headers, workflow_id: str, deadline_s: float = 45):
    resp = client.post(f"/api/workflows/{workflow_id}/run", json={}, headers=headers)
    assert resp.status_code == 202, resp.text
    execution_id = resp.json()["data"]["execution_id"]
    deadline = time.monotonic() + deadline_s
    data: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("running", "queued", "cancelling"):
            return execution_id, data
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish: {data['status']}")


def _summary(data: dict[str, Any]) -> dict[str, Any]:
    return data["results"]["outputs"]["summarize"]["main"][0]


def test_workflow_definition_is_valid() -> None:
    from app.engine.graph import build_graph, topological_sort, validate_graph
    from app.schemas.workflow import Workflow

    child = Workflow.model_validate(
        _load_example("salesforce_hubspot_contact_upsert.json", "sf", "hs")
    )
    parent = Workflow.model_validate(
        _load_example("salesforce_to_hubspot_contact_sync.json", "sf", "hs")
    )
    for workflow in (child, parent):
        validate_graph(workflow)
        graph = build_graph(workflow)
        assert len(topological_sort(graph)) == len(workflow.nodes)

    assert child.id == CHILD_ID
    assert parent.id == PARENT_ID
    sub = next(node for node in parent.nodes if node.id == "sync_contact")
    assert sub.parameters["workflow_id"] == CHILD_ID
    assert sub.parameters["mode"] == "onceForEach"
    assert sub.settings["continue_on_error"] is True


def test_full_sync_upserts_and_is_idempotent(client):
    headers = _setup(client)
    sf_cred = _create_credential(client, headers, "salesforce", SF_DATA, "SF Sync")
    hs_cred = _create_credential(client, headers, "hubspot", HS_DATA, "HubSpot Sync")
    _import_workflows(client, headers, sf_cred, hs_cred)

    router = RoutedVendorFake(
        [ACME_CONTACT, GLOBEX_CONTACT, UMBRELLA_CONTACT, INITECH_CONTACT],
        companies=[
            {"id": "c_acme", "properties": {"name": "Old Acme", "domain": "acme.com"}},
        ],
        contacts=[
            {
                "id": "ct_ada",
                "properties": {"email": "ada@acme.com", "firstname": "Ada", "lastname": "Lovelace"},
            },
        ],
        deals=[
            {
                "id": "d_acme",
                "properties": {"dealname": ACME_DEAL_NAME, "dealstage": "appointmentscheduled"},
            },
        ],
    )

    with route_vendor_http(router):
        _execution_id, data = _run_and_poll(client, headers, PARENT_ID)

    assert data["status"] == "success", data
    summary = _summary(data)
    assert summary["status"] == "success"
    assert summary["summary"] == {
        "fetched": 4,
        "eligible": 3,
        "skipped": 1,
        "synced": 3,
        "failed": 0,
        "companies_created": 2,
        "companies_updated": 1,
        "contacts_created": 2,
        "contacts_updated": 1,
        "deals_created": 1,
        "deals_updated": 1,
        "deals_not_applicable": 1,
        "contact_company_associations": 3,
        "deal_company_associations": 2,
    }
    by_email = {row["contact_email"]: row for row in summary["results"]}
    assert by_email["ada@acme.com"]["lead_score"] == 100
    assert by_email["ada@acme.com"]["lead_tier"] == "A"
    assert by_email["ada@acme.com"]["company_action"] == "updated"
    assert by_email["ada@acme.com"]["contact_action"] == "updated"
    assert by_email["ada@acme.com"]["deal_action"] == "updated"
    assert by_email["bob@globex.io"]["company_action"] == "created"
    assert by_email["bob@globex.io"]["contact_action"] == "created"
    assert by_email["bob@globex.io"]["deal_action"] == "created"
    assert by_email["wendy@umbrella.example"]["deal_action"] == "not_applicable"
    assert by_email["peter@initech.com"]["status"] == "skipped"
    assert by_email["peter@initech.com"]["reason"] == "missing_company_domain"

    # Normalisation and mapping reached the real HubSpot payloads.
    company_searches = router.calls_for("POST", "/crm/v3/objects/companies/search")
    assert {call["json"]["filterGroups"][0]["filters"][0]["value"] for call in company_searches} == {
        "acme.com",
        "globex.io",
        "umbrella.example",
    }
    acme_update = next(
        call
        for call in router.calls_for("PATCH", "/crm/v3/objects/companies/")
        if call["json"]["properties"].get("domain") == "acme.com"
    )
    assert acme_update["json"]["properties"]["industry"] == "COMPUTER_SOFTWARE"
    assert acme_update["json"]["properties"]["country"] == "United States"
    assert acme_update["json"]["properties"]["annualrevenue"] == "5000000"
    assert acme_update["json"]["properties"]["lifecyclestage"] == "customer"

    contact_searches = router.calls_for("POST", "/crm/v3/objects/contacts/search")
    assert {call["json"]["filterGroups"][0]["filters"][0]["value"] for call in contact_searches} == {
        "ada@acme.com",
        "bob@globex.io",
        "wendy@umbrella.example",
    }
    ada_update = next(
        call
        for call in router.calls_for("PATCH", "/crm/v3/objects/contacts/")
        if call["json"]["properties"].get("email") == "ada@acme.com"
    )
    assert ada_update["json"]["properties"]["jobtitle"] == "VP Engineering"
    assert ada_update["json"]["properties"]["hs_lead_status"] == "OPEN"
    assert ada_update["json"]["properties"]["lifecyclestage"] == "customer"

    deal_searches = router.calls_for("POST", "/crm/v3/objects/deals/search")
    assert {call["json"]["filterGroups"][0]["filters"][0]["value"] for call in deal_searches} == {
        ACME_DEAL_NAME,
        GLOBEX_DEAL_NAME,
    }
    deal_creates = [
        call
        for call in router.calls
        if call["method"] == "POST" and call["path"] == "/crm/v3/objects/deals"
    ]
    assert len(deal_creates) == 1
    assert deal_creates[0]["json"]["properties"]["dealname"] == GLOBEX_DEAL_NAME
    assert deal_creates[0]["json"]["properties"]["amount"] == "1200000"

    contact_company_assocs = [
        assoc for assoc in router.associations if assoc[0] == "contacts" and assoc[4] == "1"
    ]
    deal_company_assocs = [
        assoc for assoc in router.associations if assoc[0] == "deals" and assoc[4] == "5"
    ]
    assert len(contact_company_assocs) == 3
    assert len(deal_company_assocs) == 2
    assert len(router.companies) == 3
    assert len(router.contacts) == 3
    assert len(router.deals) == 2

    # Re-running the same sync updates existing records and creates nothing.
    with route_vendor_http(router):
        _execution_id, second = _run_and_poll(client, headers, PARENT_ID)

    assert second["status"] == "success", second
    second_summary = _summary(second)["summary"]
    assert second_summary["companies_created"] == 0
    assert second_summary["contacts_created"] == 0
    assert second_summary["deals_created"] == 0
    assert second_summary["companies_updated"] == 3
    assert second_summary["contacts_updated"] == 3
    assert second_summary["deals_updated"] == 2
    assert second_summary["deals_not_applicable"] == 1
    assert second_summary["failed"] == 0
    assert len(router.companies) == 3
    assert len(router.contacts) == 3
    assert len(router.deals) == 2


def test_company_create_failure_fails_the_run_with_a_summary(client):
    headers = _setup(client)
    sf_cred = _create_credential(client, headers, "salesforce", SF_DATA, "SF Failure")
    hs_cred = _create_credential(client, headers, "hubspot", HS_DATA, "HubSpot Failure")
    _import_workflows(client, headers, sf_cred, hs_cred)

    router = RoutedVendorFake(
        [FAILCO_CONTACT],
        fail_company_create_domains={"failco.example"},
    )
    with route_vendor_http(router):
        _execution_id, data = _run_and_poll(client, headers, PARENT_ID)

    assert data["status"] == "failed", data
    summary = _summary(data)
    assert summary["summary"]["fetched"] == 1
    assert summary["summary"]["eligible"] == 1
    assert summary["summary"]["synced"] == 0
    assert summary["summary"]["failed"] == 1
    assert summary["status"] == "error"
    assert len(router.companies) == 0
    assert data["error"]["code"] == "STOP_AND_ERROR"
