"""Universal Connector SDK — template integration tests (Phase 40).

Proves a NEW connector built from ``app/connectors/_template/`` runs
through the full engine path (registry → discovery → executor →
op_execute → normalize) with ZERO modifications to core files:

- dynamically registered on the ConnectorRegistry + credential registry
- appears in discovery
- executes via its node type end-to-end (API -> queue -> worker -> engine)
- normalize_output shapes provider data; secrets never leak to records
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.connectors import get_registry, register_builtin_connectors
from app.connectors._template.definition import build_my_connector_definition
from app.connectors._template.my_connector import MyConnectorConnector
from tests.test_api.conftest import auth_headers, register

TEMPLATE_KEY = "my_connector"

pytestmark = pytest.mark.timing


@pytest.fixture(scope="module", autouse=True)
def _register_template():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()  # base set first; template must not clash
    registry.register(MyConnectorConnector(), build_my_connector_definition())
    yield


def test_discovery_includes_template(client):
    headers = auth_headers(register(client)["token"])
    keys = [c.get("connector_key") or c.get("key") for c in client.get("/api/connectors", headers=headers).json()["data"]]
    assert TEMPLATE_KEY in keys


class FakeHTTPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(self, method, url, **kwargs) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        return httpx.Response(
            200,
            json={"id": "res_1", "name": "Thing"},
            request=httpx.Request(method, url),
        )


def test_template_node_executes_end_to_end(client, monkeypatch):
    """Full stack with a patched SafeHTTPClient seam. The template's
    credential type is registered dynamically here exactly as a real
    connector would add it to app.credentials.registry."""
    from pydantic import BaseModel

    from app.credentials.registry import CREDENTIAL_TYPES, SECRET_FIELDS

    class TplCredential(BaseModel):
        api_key: str = ""

    monkeypatch.setitem(CREDENTIAL_TYPES, TEMPLATE_KEY, TplCredential)
    monkeypatch.setitem(SECRET_FIELDS, TEMPLATE_KEY, frozenset({"api_key"}))

    headers = auth_headers(register(client)["token"])
    cred = client.post(
        "/api/credentials",
        json={"name": "Tpl Cred", "type": TEMPLATE_KEY, "data": {"api_key": "TPL_API_KEY_SECRET"}},
        headers=headers,
    )
    assert cred.status_code == 201, cred.text
    cred_id = cred.json()["data"]["id"]

    wf = {
        "id": "wf_tpl",
        "name": "Template flow",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "tpl",
                "type": TEMPLATE_KEY,
                "parameters": {"operation": "fetch", "resource_id": "res_1"},
                "credentials": {TEMPLATE_KEY: cred_id},
            },
        ],
        "connections": [{"source": "trigger", "target": "tpl"}],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    fake = FakeHTTPClient()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake)
    cm.__aexit__ = AsyncMock(return_value=False)
    with patch("app.connectors._template.my_connector.get_safe_http_client", return_value=cm):
        resp = client.post("/api/workflows/wf_tpl/run", json={}, headers=headers)
        assert resp.status_code == 202, resp.text
        eid = resp.json()["data"]["execution_id"]

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            data = client.get(f"/api/executions/{eid}", headers=headers).json()["data"]
            if data["status"] not in ("queued", "running", "cancelling"):
                break
            time.sleep(0.05)

    assert data["status"] == "success", data.get("error")
    out = data["results"]["outputs"]["tpl"]["main"][0]
    assert out == {"id": "res_1", "name": "Thing", "normalized": True}
    raw = json.dumps(data, default=str)
    assert "TPL_API_KEY_SECRET" not in raw
