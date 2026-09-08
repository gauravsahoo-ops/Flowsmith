"""Files API tests (Phase 19-20): upload, list, download, delete, workspace isolation."""

import io

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _auth_header(client: TestClient, email: str = "files_owner@example.com", password: str = "Aa1!aaaa") -> dict:
    # Register + login helper (idempotent: register may 409 if user exists).
    client.post("/api/auth/register", json={"email": email, "password": password, "name": "Owner"})
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


def test_upload_list_download_delete_roundtrip():
    client = TestClient(app)
    headers = _auth_header(client, email="files_roundtrip@example.com")
    # Upload
    resp = client.post(
        "/api/files",
        headers=headers,
        files={"file": ("hello.txt", io.BytesIO(b"hello world"), "text/plain")},
        data={},
    )
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["data"]["id"]
    assert resp.json()["data"]["size"] == 11

    # List
    resp = client.get("/api/files", headers=headers)
    assert resp.status_code == 200
    assert any(f["id"] == file_id for f in resp.json()["data"])

    # Download
    resp = client.get(f"/api/files/{file_id}/download", headers=headers)
    assert resp.status_code == 200
    assert resp.content == b"hello world"

    # Delete
    resp = client.delete(f"/api/files/{file_id}", headers=headers)
    assert resp.status_code == 200
    # Second delete 404
    resp = client.delete(f"/api/files/{file_id}", headers=headers)
    assert resp.status_code == 404


def test_workspace_isolation_on_files():
    client = TestClient(app)
    owner_h = _auth_header(client, email="files_wsa@example.com")
    other_h = _auth_header(client, email="files_wsb@example.com")

    # Owner uploads a personal file (no workspace)
    resp = client.post(
        "/api/files",
        headers=owner_h,
        files={"file": ("secret.txt", io.BytesIO(b"secret"), "text/plain")},
    )
    assert resp.status_code == 201
    fid = resp.json()["data"]["id"]

    # Other user should not be able to download it (owner-only)
    resp = client.get(f"/api/files/{fid}/download", headers=other_h)
    assert resp.status_code == 403
