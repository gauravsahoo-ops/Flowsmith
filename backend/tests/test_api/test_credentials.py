"""Credential endpoint tests (spec 12, 29): CRUD, encryption at rest,
never-return-data, isolation, validation."""

from __future__ import annotations

from app.db import get_session
from app.models import Credential
from app.security.crypto import decrypt_text
from tests.test_api.conftest import auth_headers, register

SMTP_DATA = {"host": "smtp.example.com", "port": 587, "username": "u", "password": "s3cret!"}


def _setup(client):
    return auth_headers(register(client)["token"])


def _create(client, headers, name="My SMTP", type_="smtp", data=SMTP_DATA):
    resp = client.post(
        "/api/credentials",
        json={"name": name, "type": type_, "data": data},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def test_create_and_list_returns_metadata_only(client):
    headers = _setup(client)
    meta = _create(client, headers)
    assert set(meta) == {"id", "name", "type"}
    assert meta["name"] == "My SMTP"
    assert meta["type"] == "smtp"

    listed = client.get("/api/credentials", headers=headers).json()["data"]
    assert listed == [meta]


def test_create_requires_auth(client):
    assert client.post("/api/credentials", json={"name": "x", "type": "smtp", "data": SMTP_DATA}).status_code == 401


def test_create_rejects_unknown_type(client):
    headers = _setup(client)
    resp = client.post(
        "/api/credentials",
        json={"name": "x", "type": "slack", "data": {}},
        headers=headers,
    )
    assert resp.status_code == 422


def test_create_validates_data(client):
    headers = _setup(client)
    resp = client.post(
        "/api/credentials",
        json={"name": "x", "type": "smtp", "data": {"host": ""}},
        headers=headers,
    )
    assert resp.status_code == 422


def test_stored_blob_is_encrypted_and_round_trips(client):
    headers = _setup(client)
    meta = _create(client, headers, data={"host": "smtp.example.com", "password": "topsecret"})

    db = get_session()
    try:
        rec = db.get(Credential, meta["id"])
        assert rec is not None
        assert b"topsecret" not in rec.data
        assert b"smtp.example.com" not in rec.data
        assert "topsecret" not in str(rec.data)
        import json

        decrypted = json.loads(decrypt_text(rec.data))
        assert decrypted["password"] == "topsecret"
    finally:
        db.close()


def test_delete(client):
    headers = _setup(client)
    meta = _create(client, headers)
    assert client.delete(f"/api/credentials/{meta['id']}", headers=headers).status_code == 204
    assert client.get("/api/credentials", headers=headers).json()["data"] == []


def test_delete_foreign_credential_404(client):
    headers = _setup(client)
    meta = _create(client, headers)
    token_b = register(client, email="b@b.com", password="Password123!")["token"]
    assert client.delete(f"/api/credentials/{meta['id']}", headers=auth_headers(token_b)).status_code == 404


def test_list_isolated_between_users(client):
    headers_a = _setup(client)
    _create(client, headers_a)
    token_b = register(client, email="c@c.com", password="Password123!")["token"]
    assert client.get("/api/credentials", headers=auth_headers(token_b)).json()["data"] == []


def test_credential_types_catalog(client):
    headers = _setup(client)
    types = client.get("/api/credentials/types", headers=headers).json()["data"]
    kinds = {t["type"] for t in types}
    assert {"smtp", "database", "http", "llm", "salesforce"} <= kinds
    smtp = next(t for t in types if t["type"] == "smtp")
    assert "host" in smtp["parameters_schema"]["properties"]
    assert smtp["secret_fields"] == ["password"]
    http = next(t for t in types if t["type"] == "http")
    assert set(http["secret_fields"]) == {"api_key", "password"}
    sf = next(t for t in types if t["type"] == "salesforce")
    assert set(sf["secret_fields"]) == {"client_secret", "password", "refresh_token"}
    assert "instance_url" in sf["parameters_schema"]["properties"]


def test_create_salesforce_credential_roundtrip(client):
    headers = _setup(client)
    data = {
        "instance_url": "https://login.salesforce.com",
        "client_id": "cid",
        "client_secret": "secret",
        "username": "u@example.com",
        "password": "pw+token",
    }
    resp = client.post("/api/credentials", json={"name": "SF", "type": "salesforce", "data": data}, headers=headers)
    assert resp.status_code == 201, resp.text
    meta = resp.json()["data"]
    assert set(meta) == {"id", "name", "type"}

    # Metadata only: decrypted payload must round-trip, never be echoed
    from app.db import get_session
    from app.models import Credential
    from app.security.crypto import decrypt_text

    db = get_session()
    rec = db.get(Credential, meta["id"])
    assert rec is not None
    plaintext = decrypt_text(rec.data)
    assert '"client_secret": "secret"' in plaintext
    db.close()
