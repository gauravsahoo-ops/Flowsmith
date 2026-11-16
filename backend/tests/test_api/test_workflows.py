"""Workflow CRUD tests (spec 51.4: CRUD, validation, conflict, authz)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.db import get_session
from app.models import WorkflowRecord
from tests.test_api.conftest import auth_headers, make_workflow, register


def _setup(client):
    return auth_headers(register(client)["token"])


def test_create_workflow(client):
    headers = _setup(client)
    resp = client.post("/api/workflows", json=make_workflow(), headers=headers)
    assert resp.status_code == 201
    assert resp.json()["data"]["id"] == "wf_1"
    assert resp.json()["data"]["version"] == 1


def test_create_duplicate_id_conflicts(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    resp = client.post("/api/workflows", json=make_workflow(), headers=headers)
    assert resp.status_code == 409


def test_create_cyclic_graph_allowed(client):
    """Cycles are now tolerated by the engine (cycle-breaking semantics)."""
    headers = _setup(client)
    wf = make_workflow()
    wf["connections"] = [
        {"source": "trigger", "target": "transform"},
        {"source": "transform", "target": "trigger"},
    ]
    resp = client.post("/api/workflows", json=wf, headers=headers)
    assert resp.status_code == 201


def test_create_unknown_node_type_rejected(client):
    headers = _setup(client)
    wf = make_workflow()
    wf["nodes"][1]["type"] = "does_not_exist"
    resp = client.post("/api/workflows", json=wf, headers=headers)
    assert resp.status_code == 422


def test_create_duplicate_node_ids_rejected(client):
    headers = _setup(client)
    wf = make_workflow()
    wf["nodes"].append({"id": "trigger", "type": "manual_trigger", "parameters": {}})
    resp = client.post("/api/workflows", json=wf, headers=headers)
    assert resp.status_code == 422


def test_get_workflow(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    resp = client.get("/api/workflows/wf_1", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "My Workflow"


def test_get_missing_workflow_404(client):
    headers = _setup(client)
    assert client.get("/api/workflows/nope", headers=headers).status_code == 404


def test_list_workflows_paginated(client):
    headers = _setup(client)
    for i in range(3):
        wf = make_workflow(workflow_id=f"wf_{i}", name=f"WF {i}")
        client.post("/api/workflows", json=wf, headers=headers)
    resp = client.get("/api/workflows?page=1&pageSize=2", headers=headers)
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["meta"] == {"page": 1, "pageSize": 2, "total": 3}


def test_update_bumps_version(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    wf = make_workflow(name="Renamed")
    resp = client.put("/api/workflows/wf_1", json=wf, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["version"] == 2
    assert resp.json()["data"]["name"] == "Renamed"


def test_save_persists_exact_payload_round_trip(client):
    """Save (PUT) persists nodes/connections/name exactly; GET returns them
    unchanged after a refresh-style reload (browser refresh must not lose data)."""
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)

    wf = make_workflow(name="Saved Workflow")
    wf["nodes"] = [
        {"id": "trigger", "type": "manual_trigger", "parameters": {}, "settings": {}},
        {"id": "transform", "type": "set_data", "parameters": {"fields": {"who": "hi"}}, "settings": {}},
    ]
    wf["connections"] = [{"source": "trigger", "target": "transform"}]
    resp = client.put("/api/workflows/wf_1", json=wf, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["version"] == 2

    # Simulate a browser refresh: fresh GET must return exactly what was saved.
    saved = client.get("/api/workflows/wf_1", headers=headers).json()["data"]
    assert saved["name"] == "Saved Workflow"
    assert saved["version"] == 2
    assert [n["id"] for n in saved["nodes"]] == ["trigger", "transform"]
    assert saved["nodes"][1]["parameters"] == {"fields": {"who": "hi"}}
    assert saved["connections"] == [{"source": "trigger", "sourceHandle": "main", "target": "transform", "targetHandle": "main"}]


def test_save_creates_immutable_version_snapshots(client):
    """Each save appends an immutable workflow_versions row; the latest is active."""
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    for i in range(2, 4):
        wf = make_workflow(name=f"v{i}")
        assert client.put("/api/workflows/wf_1", json=wf, headers=headers).json()["data"]["version"] == i

    versions = client.get("/api/workflows/wf_1/versions", headers=headers).json()["data"]
    assert [v["version"] for v in versions] == [3, 2, 1]
    assert versions[0]["is_active"] is True
    assert versions[1]["is_active"] is False
    assert versions[2]["is_active"] is False


def test_rollback_restores_saved_version(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    wf = make_workflow(name="v2")
    client.put("/api/workflows/wf_1", json=wf, headers=headers)

    resp = client.post("/api/workflows/wf_1/rollback", json={"version": 1}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["version"] == 3
    assert resp.json()["data"]["name"] == "My Workflow"
    assert client.get("/api/workflows/wf_1", headers=headers).json()["data"]["name"] == "My Workflow"


def test_save_requires_authentication(client):
    wf = make_workflow()
    assert client.put("/api/workflows/wf_1", json=wf).status_code == 401
    assert client.post("/api/workflows", json=wf).status_code == 401


def test_list_workflows_rejects_invalid_pagination(client):
    headers = _setup(client)
    assert client.get("/api/workflows?page=0", headers=headers).status_code == 422
    assert client.get("/api/workflows?pageSize=0", headers=headers).status_code == 422


def test_stale_save_with_version_is_rejected(client):
    """Optimistic concurrency: a tab that loaded v1 cannot overwrite v2."""
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)

    first = make_workflow(name="First save")
    first["version"] = 1
    saved = client.put("/api/workflows/wf_1", json=first, headers=headers)
    assert saved.status_code == 200
    assert saved.json()["data"]["version"] == 2

    stale = make_workflow(name="Stale overwrite")
    stale["version"] = 1
    conflict = client.put("/api/workflows/wf_1", json=stale, headers=headers)
    assert conflict.status_code == 409
    assert "version conflict" in conflict.json()["detail"].lower()

    current = client.get("/api/workflows/wf_1", headers=headers).json()["data"]
    assert current["version"] == 2
    assert current["name"] == "First save"


def test_save_invalid_graph_rejected_and_not_persisted(client):
    """Cycles are now tolerated; this tests an actually invalid graph (unknown type)."""
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    wf = make_workflow()
    wf["nodes"][1]["type"] = "does_not_exist"
    assert client.put("/api/workflows/wf_1", json=wf, headers=headers).status_code == 422
    saved = client.get("/api/workflows/wf_1", headers=headers).json()["data"]
    assert saved["version"] == 1


def test_update_cyclic_allowed_and_version_incremented(client):
    """Cycles are now tolerated by the engine (cycle-breaking semantics)."""
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    wf = make_workflow()
    wf["connections"] = [
        {"source": "trigger", "target": "transform"},
        {"source": "transform", "target": "trigger"},
    ]
    assert client.put("/api/workflows/wf_1", json=wf, headers=headers).status_code == 200
    assert client.get("/api/workflows/wf_1", headers=headers).json()["data"]["version"] == 2


def test_update_id_mismatch_conflicts(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    wf = make_workflow(workflow_id="other_id")
    assert client.put("/api/workflows/wf_1", json=wf, headers=headers).status_code == 409


def test_patch_active(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    resp = client.patch("/api/workflows/wf_1/active", json={"active": True}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["active"] is True
    assert client.get("/api/workflows/wf_1", headers=headers).json()["data"]["active"] is True


def test_patch_active_requires_bool(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    assert client.patch("/api/workflows/wf_1/active", json={"active": "yes"}, headers=headers).status_code == 422


def test_delete_workflow(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    assert client.delete("/api/workflows/wf_1", headers=headers).status_code == 204
    assert client.get("/api/workflows/wf_1", headers=headers).status_code == 404


def test_create_draft_with_unconfigured_node_succeeds(client):
    """Phase 24 draft semantics: an unconfigured node (UI default params)
    must not block saving — parameter validation happens at run time."""
    headers = _setup(client)
    wf = make_workflow()
    wf["nodes"].append({
        "id": "cond",
        "type": "if_condition",
        "parameters": {"condition": {}},  # empty: UI default for object params
        "settings": {},
    })
    wf["connections"] = [
        {"source": "trigger", "target": "transform"},
        {"source": "transform", "target": "cond"},
    ]
    resp = client.post("/api/workflows", json=wf, headers=headers)
    assert resp.status_code == 201
    saved = client.get("/api/workflows/wf_1", headers=headers).json()["data"]
    assert any(n["id"] == "cond" for n in saved["nodes"])


def test_update_draft_with_unconfigured_node_succeeds(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    wf = make_workflow(name="Draft")
    wf["nodes"].append({
        "id": "cond",
        "type": "if_condition",
        "parameters": {"condition": {}},
        "settings": {},
    })
    wf["connections"] = [{"source": "trigger", "target": "transform"},
                         {"source": "transform", "target": "cond"}]
    resp = client.put("/api/workflows/wf_1", json=wf, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["version"] == 2


def test_tenant_isolation(client):
    headers_a = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers_a)
    token_b = register(client, email="b@b.com", password="Password123!")["token"]
    headers_b = auth_headers(token_b)
    assert client.get("/api/workflows", headers=headers_b).json()["meta"]["total"] == 0
    assert client.get("/api/workflows/wf_1", headers=headers_b).status_code == 404
    assert client.put("/api/workflows/wf_1", json=make_workflow(), headers=headers_b).status_code == 404
    assert client.delete("/api/workflows/wf_1", headers=headers_b).status_code == 404
def test_workflow_versions_and_history(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(name="Original"), headers=headers)
    wf2 = make_workflow(name="Updated")
    client.put("/api/workflows/wf_1", json=wf2, headers=headers)

    # 1. list versions
    v_res = client.get("/api/workflows/wf_1/versions", headers=headers)
    assert v_res.status_code == 200
    versions = v_res.json()["data"]
    assert len(versions) == 2
    assert versions[0]["version"] == 2
    assert "author_name" in versions[0]
    assert "author_email" in versions[0]
    assert "node_count" in versions[0]

    # 2. get specific version detail
    v1_res = client.get("/api/workflows/wf_1/versions/1", headers=headers)
    assert v1_res.status_code == 200
    assert v1_res.json()["data"]["name"] == "Original"
    assert "data" in v1_res.json()["data"]

    # 3. rollback
    rb_res = client.post("/api/workflows/wf_1/rollback", json={"version": 1}, headers=headers)
    assert rb_res.status_code == 200
    assert rb_res.json()["data"]["name"] == "Original"
    assert rb_res.json()["data"]["version"] == 3

    # 4. activation history
    client.patch("/api/workflows/wf_1/active", json={"active": True}, headers=headers)
    client.patch("/api/workflows/wf_1/active", json={"active": False}, headers=headers)
    act_res = client.get("/api/workflows/wf_1/activation-history", headers=headers)
    assert act_res.status_code == 200
    timeline = act_res.json()["data"]
    assert len(timeline) >= 2
    assert any(item["action"] == "activated" for item in timeline)
    assert any(item["action"] == "deactivated" for item in timeline)


def test_set_pinned(client):
    headers = _setup(client)
    wf = make_workflow(name="Pin Test")
    client.post("/api/workflows", json=wf, headers=headers)
    res = client.patch(f"/api/workflows/{wf['id']}/pinned", json={"pinned": True}, headers=headers)
    assert res.status_code == 200
    assert res.json()["data"]["pinned"] is True

    get_res = client.get(f"/api/workflows/{wf['id']}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["data"]["pinned"] is True

    unpin_res = client.patch(f"/api/workflows/{wf['id']}/pinned", json={"pinned": False}, headers=headers)
    assert unpin_res.status_code == 200
    assert unpin_res.json()["data"]["pinned"] is False


def test_list_workflows_envelope_and_updated_at_order(client):
    headers = _setup(client)
    for i in range(3):
        wf = make_workflow(workflow_id=f"wf_order_{i}", name=f"Order {i}")
        assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    now = datetime.now(UTC)
    with get_session() as db:
        for workflow_id, updated_at in (
            ("wf_order_0", now - timedelta(hours=2)),
            ("wf_order_1", now - timedelta(hours=1)),
            ("wf_order_2", now),
        ):
            db.execute(
                update(WorkflowRecord)
                .where(WorkflowRecord.id == workflow_id)
                .values(updated_at=updated_at)
            )
        db.commit()

    first = client.get("/api/workflows?page=1&pageSize=2", headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert set(body) == {"data", "meta"}
    assert [row["id"] for row in body["data"]] == ["wf_order_2", "wf_order_1"]
    assert body["meta"] == {"page": 1, "pageSize": 2, "total": 3}

    second = client.get("/api/workflows?page=2&pageSize=2", headers=headers)
    assert second.status_code == 200, second.text
    assert [row["id"] for row in second.json()["data"]] == ["wf_order_0"]
    assert second.json()["meta"] == {"page": 2, "pageSize": 2, "total": 3}


def test_versions_require_edit_permission_and_activation_history_visibility(client):
    owner = register(client, email="version-owner@example.com")
    viewer = register(client, email="version-viewer@example.com")
    editor = register(client, email="version-editor@example.com")
    outsider = register(client, email="version-outsider@example.com")
    owner_headers = auth_headers(owner["token"])
    viewer_headers = auth_headers(viewer["token"])
    editor_headers = auth_headers(editor["token"])
    outsider_headers = auth_headers(outsider["token"])

    created = client.post("/api/workflows", json=make_workflow(), headers=owner_headers)
    assert created.status_code == 201, created.text
    wf_id = created.json()["data"]["id"]

    for email, permission in (
        (viewer["user"]["email"], "view"),
        (editor["user"]["email"], "edit"),
    ):
        share = client.post(
            f"/api/workflows/{wf_id}/shares",
            json={"email": email, "permission": permission},
            headers=owner_headers,
        )
        assert share.status_code == 201, share.text

    for headers in (owner_headers, editor_headers):
        versions = client.get(f"/api/workflows/{wf_id}/versions", headers=headers)
        assert versions.status_code == 200, versions.text
        assert [row["version"] for row in versions.json()["data"]] == [1]
        detail = client.get(
            f"/api/workflows/{wf_id}/versions/1", headers=headers
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["version"] == 1

    for headers in (viewer_headers, outsider_headers):
        assert (
            client.get(f"/api/workflows/{wf_id}/versions", headers=headers).status_code
            == 404
        )
        assert (
            client.get(
                f"/api/workflows/{wf_id}/versions/1", headers=headers
            ).status_code
            == 404
        )

    # Activation history follows view access, not edit access.
    assert (
        client.get(
            f"/api/workflows/{wf_id}/activation-history", headers=viewer_headers
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/workflows/{wf_id}/activation-history", headers=outsider_headers
        ).status_code
        == 404
    )


def test_list_shares_requires_edit_permission(client):
    owner = register(client, email="share-owner@example.com")
    viewer = register(client, email="share-viewer@example.com")
    editor = register(client, email="share-editor@example.com")
    outsider = register(client, email="share-outsider@example.com")
    owner_headers = auth_headers(owner["token"])
    viewer_headers = auth_headers(viewer["token"])
    editor_headers = auth_headers(editor["token"])
    outsider_headers = auth_headers(outsider["token"])

    created = client.post("/api/workflows", json=make_workflow(), headers=owner_headers)
    assert created.status_code == 201, created.text
    wf_id = created.json()["data"]["id"]

    for email, permission in (
        (viewer["user"]["email"], "view"),
        (editor["user"]["email"], "edit"),
    ):
        share = client.post(
            f"/api/workflows/{wf_id}/shares",
            json={"email": email, "permission": permission},
            headers=owner_headers,
        )
        assert share.status_code == 201, share.text

    for headers in (owner_headers, editor_headers):
        response = client.get(f"/api/workflows/{wf_id}/shares", headers=headers)
        assert response.status_code == 200, response.text
        rows = response.json()["data"]
        assert {
            (row["user_id"], row["email"], row["permission"]) for row in rows
        } == {
            (
                viewer["user"]["id"],
                viewer["user"]["email"],
                "view",
            ),
            (
                editor["user"]["id"],
                editor["user"]["email"],
                "edit",
            ),
        }

    for headers in (viewer_headers, outsider_headers):
        assert (
            client.get(f"/api/workflows/{wf_id}/shares", headers=headers).status_code
            == 404
        )

