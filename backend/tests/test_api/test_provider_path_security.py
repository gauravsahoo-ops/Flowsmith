"""Security regression tests for provider trigger callback paths."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db import get_session
from app.models import User, WebhookTrigger, WorkflowRecord
from app.triggers.registry import sync_webhooks
from tests.test_api.conftest import auth_headers, register


def _workflow(workflow_id: str, node_type: str, path: str) -> dict:
    return {
        "id": workflow_id,
        "name": "Provider path security",
        "nodes": [{
            "id": "trigger",
            "type": node_type,
            "parameters": {"path": path, "method": "POST"},
        }],
        "connections": [],
        "settings": {},
    }


def _create(client, headers: dict, workflow_id: str, node_type: str, path: str):
    return client.post(
        "/api/workflows",
        json=_workflow(workflow_id, node_type, path),
        headers=headers,
    )


def test_provider_paths_require_entropy_and_single_segments(client):
    user = register(client)
    headers = auth_headers(user["token"])
    for index, path in enumerate(("x", "short-provider", "has space in provider path")):
        response = _create(client, headers, f"wf_bad_path_{index}", "github_trigger", path)
        assert response.status_code == 422, (path, response.text)
        assert "too weak" in response.json()["detail"].lower()
    slash = _create(
        client, headers, "wf_bad_slash", "github_trigger", "provider/path-with-enough-length"
    )
    assert slash.status_code == 422
    assert "single url segment" in slash.json()["detail"].lower()
    traversal = _create(
        client, headers, "wf_bad_segments", "webhook", "a" * 21 + "/.."
    )
    assert traversal.status_code == 422
    assert "must not contain" in traversal.json()["detail"].lower()


def test_provider_path_collision_is_rejected_on_activation(client):
    first = register(client)
    second = register(client)
    first_headers = auth_headers(first["token"])
    second_headers = auth_headers(second["token"])
    path = f"provider-collision-{uuid.uuid4().hex[:24]}"

    assert _create(client, first_headers, "wf_collision_first", "github_trigger", path).status_code == 201
    # Both may exist as drafts; activation is where the live path is claimed.
    assert _create(client, second_headers, "wf_collision_second", "github_trigger", path).status_code == 201
    assert client.patch(
        "/api/workflows/wf_collision_first/active", json={"active": True}, headers=first_headers
    ).status_code == 200
    blocked = client.patch(
        "/api/workflows/wf_collision_second/active", json={"active": True}, headers=second_headers
    )
    assert blocked.status_code == 422
    assert "already used" in blocked.json()["detail"].lower()

    db = get_session()
    try:
        rows = db.scalars(select(WebhookTrigger).where(WebhookTrigger.path == path)).all()
        assert len(rows) == 1
        assert rows[0].workflow_id == "wf_collision_first"
    finally:
        db.close()


def test_duplicate_and_import_regenerate_provider_paths(client):
    user = register(client)
    headers = auth_headers(user["token"])
    path = f"provider-regenerate-{uuid.uuid4().hex[:24]}"
    assert _create(client, headers, "wf_provider_source", "github_trigger", path).status_code == 201

    duplicated = client.post("/api/workflows/wf_provider_source/duplicate", headers=headers)
    assert duplicated.status_code == 201, duplicated.text
    duplicated_nodes = duplicated.json()["data"]["nodes"]
    duplicated_path = duplicated_nodes[0]["parameters"]["path"]
    assert duplicated_path != path
    assert len(duplicated_path) >= 24

    imported = client.post(
        "/api/workflows/import",
        json=_workflow("wf_provider_import_source", "github_trigger", path),
        headers=headers,
    )
    assert imported.status_code == 201, imported.text
    imported_nodes = imported.json()["data"]["nodes"]
    imported_path = imported_nodes[0]["parameters"]["path"]
    assert imported_path != path
    assert len(imported_path) >= 24


def test_same_workflow_cannot_declare_path_twice(client):
    user = register(client)
    headers = auth_headers(user["token"])
    path = f"provider-duplicate-node-{uuid.uuid4().hex[:24]}"
    workflow = {
        "id": "wf_duplicate_provider_nodes",
        "name": "Duplicate provider nodes",
        "nodes": [
            {"id": "one", "type": "github_trigger", "parameters": {"path": path}},
            {"id": "two", "type": "stripe_trigger", "parameters": {"path": path}},
        ],
        "connections": [],
        "settings": {},
    }
    response = client.post("/api/workflows", json=workflow, headers=headers)
    assert response.status_code == 422
    assert "already used" in response.json()["detail"].lower()


def test_sync_does_not_steal_an_active_path(client):
    user = register(client)
    db = get_session()
    try:
        owner = db.scalar(select(User).where(User.email == user["user"]["email"]))
        assert owner is not None
        path = f"provider-sync-owner-{uuid.uuid4().hex[:24]}"
        db.add(WorkflowRecord(
            id="wf_sync_owner",
            user_id=owner.id,
            name="Owner",
            version=1,
            active=True,
            data=_workflow("wf_sync_owner", "github_trigger", path),
        ))
        db.commit()
        sync_webhooks(db)
        first = db.scalar(select(WebhookTrigger).where(WebhookTrigger.path == path))
        assert first is not None
        assert first.workflow_id == "wf_sync_owner"

        db.add(WorkflowRecord(
            id="wf_sync_claimant",
            user_id=owner.id,
            name="Claimant",
            version=1,
            active=True,
            data=_workflow("wf_sync_claimant", "github_trigger", path),
        ))
        db.commit()
        sync_webhooks(db)
        row = db.scalar(select(WebhookTrigger).where(WebhookTrigger.path == path))
        assert row is not None
        assert row.workflow_id == "wf_sync_owner"
    finally:
        db.close()
