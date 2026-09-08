"""Template library tests (Phase 36): update/delete, is_mine, seeding."""

from __future__ import annotations

import pytest

from tests.test_api.conftest import auth_headers, register


def _headers(client):
    return auth_headers(register(client)["token"])


def _make_template(client, headers, name="My T", **kw):
    payload = {
        "name": name,
        "description": kw.get("description", ""),
        "category": kw.get("category", "general"),
        "workflow_data": {
            "nodes": [{"id": "t", "type": "manual_trigger", "parameters": {}}],
            "connections": [],
        },
        "is_public": kw.get("is_public", False),
    }
    resp = client.post("/api/templates", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_update_template_metadata(client):
    headers = _headers(client)
    t = _make_template(client, headers)
    resp = client.patch(
        f"/api/templates/{t['id']}",
        json={"name": "Renamed", "is_public": True},
        headers=headers,
    )
    assert resp.status_code == 200
    body = client.get("/api/templates", headers=headers).json()["data"]
    row = next(r for r in body if r["id"] == t["id"])
    assert row["name"] == "Renamed"
    assert row["is_public"] is True
    assert row["is_mine"] is True


def test_update_requires_creator(client):
    owner = _headers(client)
    t = _make_template(client, owner)
    other = auth_headers(register(client, email="tmpl-other@x.com")["token"])
    resp = client.patch(f"/api/templates/{t['id']}", json={"name": "hijack"}, headers=other)
    assert resp.status_code == 404


def test_delete_template(client):
    owner = _headers(client)
    t = _make_template(client, owner)
    other = auth_headers(register(client, email="tmpl-del@x.com")["token"])
    assert client.delete(f"/api/templates/{t['id']}", headers=other).status_code == 404
    assert client.delete(f"/api/templates/{t['id']}", headers=owner).status_code == 200
    ids = [r["id"] for r in client.get("/api/templates", headers=owner).json()["data"]]
    assert t["id"] not in ids


@pytest.mark.timing
def test_seed_script_is_idempotent(client):
    """Running the seeder twice updates in place (no duplicates by name)."""
    import os
    import pathlib
    import subprocess
    import sys

    from app.db import get_session
    from app.models import WorkflowTemplate
    from tests.conftest import TEST_DB_URL

    for _ in range(2):
        script = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "seed_templates.py"
        r = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "DATABASE_URL": TEST_DB_URL, "PYTHONPATH": str(pathlib.Path(__file__).resolve().parents[2])},
        )
        assert r.returncode == 0, r.stderr[-500:]
        db = get_session()
        try:
            names = [n for (n,) in db.query(WorkflowTemplate.name).all()]
        finally:
            db.close()
    assert len(names) == len(set(names)), f"duplicate seeded names: {names}"
    assert "Salesforce Lead Sync" in names


def test_save_as_template_shape_imports_cleanly(client):
    """The TopBar saves the full _to_dict document (extra keys included);
    using it through the import endpoint must still succeed."""
    headers = _headers(client)
    wf = {
        "id": "wf_tmpl_src",
        "name": "Source",
        "nodes": [
            {"id": "t", "type": "manual_trigger", "parameters": {}},
            {"id": "s", "type": "set_data", "parameters": {"fields": {"a": 1}}},
        ],
        "connections": [{"source": "t", "target": "s"}],
        "settings": {},
        "version": 1,
        "active": False,
        "permission": "owner",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    t = _make_template(client, headers, name="Shape T", **{"workflow_data": None}) if False else None
    resp = client.post(
        "/api/templates",
        json={"name": "Shape T", "description": "", "category": "general",
              "workflow_data": wf, "is_public": True},
        headers=headers,
    )
    assert resp.status_code == 200
    tid = resp.json()["data"]["id"]

    used = client.post(f"/api/templates/{tid}/use", headers=headers).json()["data"]
    # The real TopBar flow: the source workflow already exists for this
    # user, so import must assign a FRESH id instead of clobbering it.
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201
    imported = client.post("/api/workflows/import", json=used["workflow_data"], headers=headers)
    assert imported.status_code in (200, 201), imported.text[:300]
    new_id = imported.json()["data"]["id"]
    assert new_id != "wf_tmpl_src"


def test_all_default_templates_can_be_used_and_imported(client):
    """Verify that every default public template can be loaded and imported into a new workflow."""
    headers = _headers(client)
    templates = client.get("/api/templates", headers=headers).json()["data"]
    assert len(templates) >= 5

    for tmpl in templates:
        tid = tmpl["id"]
        used_resp = client.post(f"/api/templates/{tid}/use", headers=headers)
        assert used_resp.status_code == 200, used_resp.text
        workflow_data = used_resp.json()["data"]["workflow_data"]

        imported_resp = client.post("/api/workflows/import", json=workflow_data, headers=headers)
        assert imported_resp.status_code == 201, f"Failed importing {tmpl['name']}: {imported_resp.text}"
        imported_wf = imported_resp.json()["data"]
        assert imported_wf["id"].startswith("wf_import_")
        assert len(imported_wf["nodes"]) > 0
        assert isinstance(imported_wf["connections"], list)
