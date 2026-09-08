"""Live Salesforce schema/object discovery API tests (Phase 9).

The discovery endpoints run the registered connector's describe/list
operations against the caller's Salesforce credential. Network I/O is
mocked at the same seam as every other Salesforce suite
(`app.providers.salesforce.get_safe_http_client`), so these tests prove
routing, credential resolution, caching and error mapping — not the org.

A real-org variant of this surface lives in
tests/integration/test_salesforce_live.py (env-gated).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.api import salesforce_discovery
from app.connectors import get_registry, register_builtin_connectors
from tests.test_api.conftest import auth_headers, register


def _setup(client):
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    return auth_headers(register(client)["token"])


class FakeSFHTTP:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: Any) -> None:
        pass

    async def request(self, method, url, **kwargs) -> httpx.Response:
        self.calls.append((method, url))
        return self.responses.pop(0)


def _patch(responses: list[httpx.Response]):
    fake = FakeSFHTTP(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.providers.salesforce.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher, fake


TOKEN = {"access_token": "tok", "instance_url": "https://myorg.salesforce.com"}
SOBJECTS = {
    "sobjects": [
        {"name": "Account", "label": "Account", "createable": True},
        {"name": "Lead", "label": "Lead", "createable": True},
        {"name": "Audit_History", "label": "Audit History", "createable": False},
    ]
}
DESCRIBE = {
    "name": "Lead",
    "label": "Lead",
    "createable": True,
    "updateable": True,
    "fields": [
        {"name": "Id", "label": "Lead ID", "type": "id",
         "createable": False, "updateable": False, "nillable": False},
        {"name": "Company", "label": "Company", "type": "string",
         "createable": True, "updateable": True, "nillable": False,
         "defaultedOnCreate": False},
        {"name": "Industry", "label": "Industry", "type": "picklist",
         "createable": True, "updateable": True, "nillable": True,
         "picklistValues": [{"value": "Tech"}, {"value": "Finance"}]},
    ],
}


@pytest.fixture(autouse=True)
def _fresh_cache():
    salesforce_discovery.clear_discovery_cache()
    yield
    salesforce_discovery.clear_discovery_cache()


def _make_credential(client, headers) -> str:
    resp = client.post("/api/credentials", json={
        "name": "SF Discovery",
        "type": "salesforce",
        "data": {
            "instance_url": "https://login.salesforce.com",
            "client_id": "cid",
            "client_secret": "csecret",
            "username": "user@example.com",
            "password": "pass+token",
            "api_version": "v63.0",
        },
    }, headers=headers)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["data"]["id"]


def test_objects_requires_auth(client):
    resp = client.get("/api/connectors/salesforce/objects")
    assert resp.status_code == 401


def test_objects_without_credential_is_typed_404(client):
    headers = _setup(client)
    resp = client.get("/api/connectors/salesforce/objects", headers=headers)
    assert resp.status_code == 404
    body = resp.json()
    detail = body.get("detail") or body
    assert detail["code"] == "NO_CREDENTIAL"


def test_objects_lists_org_sobjects(client):
    headers = _setup(client)
    _make_credential(client, headers)
    patcher, fake = _patch([
        httpx.Response(200, json=TOKEN, request=httpx.Request("GET", "http://fake")),
        httpx.Response(200, json=SOBJECTS, request=httpx.Request("GET", "http://fake")),
    ])
    try:
        resp = client.get("/api/connectors/salesforce/objects", headers=headers)
    finally:
        patcher.stop()

    assert resp.status_code == 200
    data = resp.json()["data"]
    names = [o["name"] for o in data["sobjects"]]
    assert names == ["Account", "Lead", "Audit_History"]
    assert data["cached"] is False
    # Auth went to login.salesforce.com; data call to the instance URL.
    assert any(url.endswith("/services/oauth2/token") for _, url in fake.calls)
    assert any(url.endswith("/services/data/v63.0/sobjects") for _, url in fake.calls)


def test_schema_describe_returns_rich_fields(client):
    headers = _setup(client)
    _make_credential(client, headers)
    patcher, fake = _patch([
        httpx.Response(200, json=TOKEN, request=httpx.Request("GET", "http://fake")),
        httpx.Response(200, json=DESCRIBE, request=httpx.Request("GET", "http://fake")),
    ])
    try:
        resp = client.get("/api/connectors/salesforce/schema/Lead", headers=headers)
    finally:
        patcher.stop()

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["object"] if "object" in data else data["name"] == "Lead"
    fields = {f["name"]: f for f in data["fields"]}
    assert fields["Company"]["required"] is True
    assert fields["Industry"]["picklist_values"] == ["Tech", "Finance"]


def test_discovery_responses_are_cached(client):
    """Second call within TTL must not re-hit Salesforce."""
    headers = _setup(client)
    _make_credential(client, headers)
    patcher, fake = _patch([
        httpx.Response(200, json=TOKEN, request=httpx.Request("GET", "http://fake")),
        httpx.Response(200, json=SOBJECTS, request=httpx.Request("GET", "http://fake")),
    ])
    try:
        first = client.get("/api/connectors/salesforce/objects", headers=headers)
        second = client.get("/api/connectors/salesforce/objects", headers=headers)
    finally:
        patcher.stop()

    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["data"]["cached"] is True
    # Only token + one data call happened despite two API requests.
    assert len(fake.calls) == 2


def test_refresh_bypasses_cache(client):
    headers = _setup(client)
    _make_credential(client, headers)

    def _two_rounds():
        return _patch([
            httpx.Response(200, json=TOKEN, request=httpx.Request("GET", "http://fake")),
            httpx.Response(200, json=SOBJECTS, request=httpx.Request("GET", "http://fake")),
        ])

    patcher1, fake1 = _two_rounds()
    try:
        client.get("/api/connectors/salesforce/objects", headers=headers)
    finally:
        patcher1.stop()

    patcher2, fake2 = _two_rounds()
    try:
        resp = client.get("/api/connectors/salesforce/objects?refresh=true", headers=headers)
    finally:
        patcher2.stop()

    assert resp.json()["data"]["cached"] is False
    # A live data round trip happened again (token itself stays cached
    # in the connector's provider across rounds).
    assert len(fake2.calls) >= 1
    assert any(url.endswith("/services/data/v63.0/sobjects") for _, url in fake2.calls)


def test_invalid_object_name_rejected_before_network(client):
    headers = _setup(client)
    _make_credential(client, headers)
    patcher, fake = _patch([])
    try:
        resp = client.get("/api/connectors/salesforce/schema/bad%20name!", headers=headers)
    finally:
        patcher.stop()
    assert resp.status_code == 422
    assert fake.calls == []


def test_unknown_object_maps_to_typed_404(client):
    headers = _setup(client)
    _make_credential(client, headers)
    patcher, _fake = _patch([
        httpx.Response(200, json=TOKEN, request=httpx.Request("GET", "http://fake")),
        httpx.Response(
            404,
            json=[{"errorCode": "INVALID_TYPE", "message": "No such object"}],
            request=httpx.Request("GET", "http://fake"),
        ),
    ])
    try:
        resp = client.get("/api/connectors/salesforce/schema/Not_An_Object__c", headers=headers)
    finally:
        patcher.stop()
    assert resp.status_code == 404


def test_bad_credentials_map_to_401_not_500(client):
    headers = _setup(client)
    _make_credential(client, headers)
    patcher, _fake = _patch([
        httpx.Response(
            400,
            json={"error": "invalid_client", "error_description": "bad client id"},
            request=httpx.Request("GET", "http://fake"),
        ),
    ])
    try:
        resp = client.get("/api/connectors/salesforce/objects", headers=headers)
    finally:
        patcher.stop()
    assert resp.status_code == 401


def test_explicit_credential_id_must_be_owned(client):
    headers = _setup(client)
    cred_id = _make_credential(client, headers)

    # Another user's credential id must not be usable.
    other_headers = auth_headers(
        register(client, email="other-user@example.com")["token"]
    )
    resp = client.get(
        f"/api/connectors/salesforce/objects?credential_id={cred_id}",
        headers=other_headers,
    )
    assert resp.status_code == 404
