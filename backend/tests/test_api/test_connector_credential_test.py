"""Live credential probes for Batch B connectors (no network).

Each provider probe runs against faked HTTP; the credential Test
endpoint is proven end-to-end for one type (trello) with the rest
covered at probe level. Failure messages never carry secrets.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http
from tests.test_api.conftest import auth_headers, register

pytestmark = [pytest.mark.timing]


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _probe(connector_id, creds):
    from app.connectors import ConnectorError

    inst = get_registry().get(connector_id)
    assert inst is not None
    return _run(inst.test_connection(creds))


def test_trello_probe_ok_and_unauthorized():
    from app.providers import trello as _  # noqa: F401 (ensures module import path)

    patcher, _ = patch_provider_http("app.providers.trello", [json_response(200, {"username": "ada"})])
    try:
        out = _probe("trello", {"api_key": "k", "api_token": "t"})
    finally:
        patcher.stop()
    assert out == {"ok": True, "message": "Connected as ada."}

    patcher, _ = patch_provider_http("app.providers.trello", [json_response(401, {})])
    try:
        out = _probe("trello", {"api_key": "k", "api_token": "t"})
    finally:
        patcher.stop()
    assert out == {"ok": False, "message": "Connection failed (CONNECTOR_AUTH_FAILED)."}


def test_asana_probe_unwraps_envelope():
    patcher, _ = patch_provider_http("app.providers.asana", [json_response(200, {"data": {"name": "Ada"}})])
    try:
        out = _probe("asana", {"access_token": "x"})
    finally:
        patcher.stop()
    assert out == {"ok": True, "message": "Connected as Ada."}


def test_linear_probe_viewer():
    patcher, _ = patch_provider_http("app.providers.linear", [json_response(200, {"data": {"viewer": {"name": "Ada"}}})])
    try:
        out = _probe("linear", {"api_key": "x"})
    finally:
        patcher.stop()
    assert out["ok"] is True and "Ada" in out["message"]


def test_calendly_probe_email():
    patcher, _ = patch_provider_http(
        "app.providers.calendly", [json_response(200, {"resource": {"email": "a@x.com"}})])
    try:
        out = _probe("calendly", {"access_token": "x"})
    finally:
        patcher.stop()
    assert out == {"ok": True, "message": "Connected as a@x.com."}


def test_gitlab_probe_username():
    patcher, _ = patch_provider_http("app.providers.gitlab", [json_response(200, {"username": "ada"})])
    try:
        out = _probe("gitlab", {"access_token": "x"})
    finally:
        patcher.stop()
    assert out == {"ok": True, "message": "Connected as ada."}


def test_zoom_probe_email():
    patcher, _ = patch_provider_http("app.providers.zoom", [json_response(200, {"email": "a@x.com"})])
    try:
        out = _probe("zoom", {"access_token": "x"})
    finally:
        patcher.stop()
    assert out == {"ok": True, "message": "Connected as a@x.com."}


def test_twilio_probe_account():
    patcher, _ = patch_provider_http("app.providers.twilio", [json_response(200, {"friendly_name": "Main"})])
    try:
        out = _probe("twilio", {"account_sid": "AC1", "auth_token": "sekret"})
    finally:
        patcher.stop()
    assert out == {"ok": True, "message": "Connected (Main)."}
    assert "sekret" not in out["message"]


def test_bitbucket_probe_display_name():
    patcher, _ = patch_provider_http("app.providers.bitbucket", [json_response(200, {"display_name": "Ada"})])
    try:
        out = _probe("bitbucket", {"access_token": "x"})
    finally:
        patcher.stop()
    assert out == {"ok": True, "message": "Connected as Ada."}


def test_credential_test_endpoint_uses_live_probe(client):
    headers = auth_headers(register(client)["token"])
    created = client.post(
        "/api/credentials",
        json={"name": "Trello", "type": "trello", "data": {"api_key": "k", "api_token": "t"}},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    cred_id = created.json()["data"]["id"]

    patcher, _ = patch_provider_http("app.providers.trello", [json_response(200, {"username": "ada"})])
    try:
        resp = client.post(f"/api/credentials/{cred_id}/test", headers=headers)
    finally:
        patcher.stop()
    assert resp.status_code == 200
    assert resp.json()["data"] == {"ok": True, "message": "Connected as ada.", "provider": "trello"}
