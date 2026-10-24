"""Connector-pack marketplace installation, signing, lifecycle tests."""

from __future__ import annotations

import base64
import copy
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from app.config import get_settings
from app.connectors import get_registry
from app.db import get_session
from app.models import ConnectorPack, ConnectorPackTombstone, User, WorkflowRecord, WorkflowTemplate
from app.services.connector_pack_signing import sha256_bytes, sign_manifest
from tests.test_api.conftest import auth_headers, register

KEY_ID = "test-pack-key"

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Pack Test API", "version": "1.0.0"},
    "servers": [{"url": "https://api.packtest.example"}],
    "paths": {
        "/items": {
            "get": {
                "operationId": "listItems",
                "summary": "List items",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}
SPEC_V2 = copy.deepcopy(SPEC)
SPEC_V2["paths"]["/health"] = {
    "get": {
        "operationId": "healthCheck",
        "summary": "Health check",
        "responses": {"200": {"description": "ok"}},
    }
}

WORKFLOW = {
    "id": "wf_pack_template",
    "name": "Pack Template",
    "nodes": [
        {"id": "trigger", "type": "manual_trigger", "parameters": {}},
        {"id": "set", "type": "set_data", "parameters": {"fields": {"hello": "world"}}},
    ],
    "connections": [{"source": "trigger", "target": "set"}],
    "settings": {},
}


def _key() -> str:
    return f"packtest_{uuid.uuid4().hex[:8]}"


def _manifest(
    key: str,
    *,
    template: dict | None = None,
    version: str = "1.2.3",
    spec: dict | None = None,
) -> dict:
    manifest = {
        "name": key,
        "display_name": "Pack Test",
        "version": version,
        "description": "A test connector pack.",
        "category": "api",
        "issued_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "spec": spec or SPEC,
    }
    if template is not None:
        manifest["templates"] = [template]
    return manifest


def _trusted_key(
    monkeypatch,
    *,
    require_signature: bool = False,
    revoked: str = "",
) -> Ed25519PrivateKey:
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "connector_pack_trusted_keys",
        json.dumps({KEY_ID: base64.b64encode(raw).decode("ascii")}),
    )
    monkeypatch.setattr(settings, "connector_pack_require_signature", require_signature)
    monkeypatch.setattr(settings, "connector_pack_revoked_keys", revoked)
    return private


def _signed(manifest: dict, private: Ed25519PrivateKey) -> dict:
    return sign_manifest(manifest, private, KEY_ID)


def _generated_path(key: str) -> Path:
    return Path(__file__).resolve().parent.parent.parent / "app" / "connectors" / "generated"


def _read_sources(key: str) -> dict[str, str]:
    generated = _generated_path(key)
    return {
        f"gen_{key}_{suffix}.py": (generated / f"gen_{key}_{suffix}.py").read_text(encoding="utf-8")
        for suffix in ("provider", "definition", "connector")
    }


def _restore_stale_sources(key: str, sources: dict[str, str]) -> None:
    from app.connectors.openapi_emit import invalidate_generated_modules, register_generated

    generated = _generated_path(key)
    generated.mkdir(parents=True, exist_ok=True)
    for filename, source in sources.items():
        (generated / filename).write_text(source, encoding="utf-8")
    get_registry().unregister(key)
    invalidate_generated_modules(key)
    register_generated(get_registry(), str(generated))


def _cleanup(key: str) -> None:
    generated = Path(__file__).resolve().parent.parent.parent / "app" / "connectors" / "generated"
    for suffix in ("provider", "definition", "connector"):
        (generated / f"gen_{key}_{suffix}.py").unlink(missing_ok=True)
    try:
        from app.connectors.openapi_emit import invalidate_generated_modules

        get_registry().unregister(key)
        invalidate_generated_modules(key)
    except Exception:
        pass


def test_install_pack_registers_connector_and_template(client):
    admin = register(client, "pack-admin@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    manifest = _manifest(key, template={
        "name": f"Pack Template {key}",
        "description": "Created by a connector pack.",
        "category": "general",
        "workflow_data": WORKFLOW,
    })
    try:
        response = client.post(
            "/api/connector-packs/install",
            json={"manifest": manifest},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["connector_key"] == key
        assert data["operations_count"] == 1
        assert data["template_count"] == 1
        assert data["signed"] is False

        connector = client.get(f"/api/connectors/{key}", headers=headers)
        assert connector.status_code == 200, connector.text

        listed = client.get("/api/connector-packs", headers=headers)
        assert listed.status_code == 200
        assert [p["connector_key"] for p in listed.json()["data"]] == [key]

        db = get_session()
        try:
            pack = db.scalar(select(ConnectorPack).where(ConnectorPack.connector_key == key))
            assert pack is not None
            assert pack.version == "1.2.3"
            assert pack.template_count == 1
            assert pack.signed is False
            template = db.scalar(
                select(WorkflowTemplate).where(
                    WorkflowTemplate.name == f"Pack Template {key}"
                )
            )
            assert template is not None
            assert template.pack_key == key
            assert template.is_public is True
            assert '"active": false' in template.workflow_data
        finally:
            db.close()

        generated = (
            Path(__file__).resolve().parent.parent.parent
            / "app"
            / "connectors"
            / "generated"
        )
        assert (generated / f"gen_{key}_connector.py").exists()
        assert (generated / f"gen_{key}_definition.py").exists()
        assert (generated / f"gen_{key}_provider.py").exists()

        # Simulate a different API/worker process: the local generated files
        # are gone and the registry has not imported the pack. Runtime loading
        # must reconstruct the connector from PostgreSQL.
        from app.services.connector_pack_runtime import clear_pack_cache, ensure_pack_connector

        get_registry().unregister(key)
        for suffix in ("provider", "definition", "connector"):
            (generated / f"gen_{key}_{suffix}.py").unlink(missing_ok=True)
        clear_pack_cache(key)
        assert ensure_pack_connector(key) is True
        assert get_registry().get_definition(key) is not None
        assert (generated / f"gen_{key}_connector.py").exists()
    finally:
        _cleanup(key)


def test_install_pack_requires_admin(client):
    register(client, "pack-first@example.com", "Password123!")
    member = register(client, "pack-member@example.com", "Password123!")
    key = _key()
    response = client.post(
        "/api/connector-packs/install",
        json={"manifest": _manifest(key)},
        headers=auth_headers(member["token"]),
    )
    assert response.status_code == 403
    _cleanup(key)


def test_duplicate_pack_is_rejected(client):
    admin = register(client, "pack-dup@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    try:
        first = client.post(
            "/api/connector-packs/install",
            json={"manifest": _manifest(key)},
            headers=headers,
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/api/connector-packs/install",
            json={"manifest": _manifest(key)},
            headers=headers,
        )
        assert second.status_code == 409
    finally:
        _cleanup(key)


def test_invalid_template_cleans_up_generated_connector(client):
    admin = register(client, "pack-invalid@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    broken = {
        "id": "wf_broken",
        "name": "Broken",
        "nodes": [{"id": "trigger", "type": "manual_trigger", "parameters": {}}],
        "connections": [{"source": "trigger", "target": "missing"}],
        "settings": {},
    }
    response = client.post(
        "/api/connector-packs/install",
        json={"manifest": _manifest(key, template={
            "name": f"Broken {key}",
            "workflow_data": broken,
        })},
        headers=headers,
    )
    assert response.status_code == 400, response.text
    assert get_registry().get_definition(key) is None
    generated = (
        Path(__file__).resolve().parent.parent.parent
        / "app"
        / "connectors"
        / "generated"
    )
    assert not (generated / f"gen_{key}_connector.py").exists()
    _cleanup(key)


def test_signed_remote_pack_install(client, monkeypatch):
    admin = register(client, "pack-url@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    private = _trusted_key(monkeypatch)
    manifest = _signed(_manifest(key), private)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return manifest

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info) -> None:
            return None

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client",
        lambda: FakeClient(),
    )
    try:
        response = client.post(
            "/api/connector-packs/install",
            json={"manifest_url": "https://packs.example/pack.json"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["signed"] is True
        assert data["signing_key_id"] == KEY_ID
        listed = client.get("/api/connector-packs", headers=headers)
        assert listed.json()["data"][0]["source_url"] == "https://packs.example/pack.json"
        assert listed.json()["data"][0]["signed"] is True
    finally:
        _cleanup(key)


def test_remote_unsigned_pack_is_rejected(client, monkeypatch):
    admin = register(client, "pack-unsigned@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    manifest = _manifest(key)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return manifest

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info) -> None:
            return None

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client",
        lambda: FakeClient(),
    )
    response = client.post(
        "/api/connector-packs/install",
        json={"manifest_url": "https://packs.example/pack.json"},
        headers=headers,
    )
    assert response.status_code == 400
    assert "signed manifest" in response.json()["detail"].lower()
    _cleanup(key)


def test_invalid_signature_is_rejected(client, monkeypatch):
    admin = register(client, "pack-badsig@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    private = _trusted_key(monkeypatch)
    manifest = _signed(_manifest(key), private)
    manifest["version"] = "9.9.9"

    response = client.post(
        "/api/connector-packs/install",
        json={"manifest": manifest},
        headers=headers,
    )
    assert response.status_code == 400
    assert "verification failed" in response.json()["detail"].lower()
    _cleanup(key)


def test_require_signature_setting_applies_to_inline(client, monkeypatch):
    admin = register(client, "pack-required@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    private = _trusted_key(monkeypatch, require_signature=True)

    unsigned = client.post(
        "/api/connector-packs/install",
        json={"manifest": _manifest(key)},
        headers=headers,
    )
    assert unsigned.status_code == 400
    try:
        signed = client.post(
            "/api/connector-packs/install",
            json={"manifest": _signed(_manifest(key), private)},
            headers=headers,
        )
        assert signed.status_code == 200, signed.text
    finally:
        _cleanup(key)


def test_signed_spec_url_requires_matching_hash(client, monkeypatch):
    admin = register(client, "pack-spec-hash@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    private = _trusted_key(monkeypatch)
    spec_text = json.dumps(SPEC, sort_keys=True, separators=(",", ":"))
    calls = {"count": 0}

    async def fake_load(spec):
        if isinstance(spec, str) and spec.startswith(("http://", "https://")):
            calls["count"] += 1
        return spec_text

    monkeypatch.setattr("app.api.connectors._load_source_text", fake_load)
    base = _manifest(key)
    base["spec"] = "https://specs.example/openapi.json"
    base["spec_sha256"] = sha256_bytes(spec_text.encode("utf-8"))

    wrong = dict(base, spec_sha256="0" * 64)
    rejected = client.post(
        "/api/connector-packs/install",
        json={"manifest": _signed(wrong, private)},
        headers=headers,
    )
    assert rejected.status_code == 400
    try:
        accepted = client.post(
            "/api/connector-packs/install",
            json={"manifest": _signed(base, private)},
            headers=headers,
        )
        assert accepted.status_code == 200, accepted.text
        assert calls["count"] == 2
    finally:
        _cleanup(key)


def test_upgrade_pack_replaces_connector_and_templates(client):
    admin = register(client, "pack-upgrade@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    template_name = f"Upgrade Template {key}"
    v1 = _manifest(key, version="1.0.0", template={
        "name": template_name,
        "description": "version one",
        "workflow_data": WORKFLOW,
    })
    v2 = _manifest(key, version="1.3.0", spec=SPEC_V2, template={
        "name": template_name,
        "description": "version two",
        "workflow_data": WORKFLOW,
    })
    try:
        installed = client.post(
            "/api/connector-packs/install",
            json={"manifest": v1},
            headers=headers,
        )
        assert installed.status_code == 200, installed.text
        assert installed.json()["data"]["operations_count"] == 1

        upgraded = client.post(
            f"/api/connector-packs/{key}/upgrade",
            json={"manifest": v2},
            headers=headers,
        )
        assert upgraded.status_code == 200, upgraded.text
        data = upgraded.json()["data"]
        assert data["version"] == "1.3.0"
        assert data["operations_count"] == 2
        assert data["template_count"] == 1

        definition = get_registry().get_definition(key)
        assert definition is not None
        assert len(definition.operations) == 2

        db = get_session()
        try:
            pack = db.scalar(select(ConnectorPack).where(ConnectorPack.connector_key == key))
            assert pack is not None
            assert pack.version == "1.3.0"
            templates = db.scalars(
                select(WorkflowTemplate).where(WorkflowTemplate.pack_key == key)
            ).all()
            assert len(templates) == 1
            assert templates[0].description == "version two"
        finally:
            db.close()

        downgrade = client.post(
            f"/api/connector-packs/{key}/upgrade",
            json={"manifest": v1},
            headers=headers,
        )
        assert downgrade.status_code == 409
    finally:
        _cleanup(key)


def test_failed_upgrade_restores_previous_connector(client):
    admin = register(client, "pack-rollback@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    template_name = f"Rollback Template {key}"
    v1 = _manifest(key, version="1.0.0", template={
        "name": template_name,
        "description": "version one",
        "workflow_data": WORKFLOW,
    })
    broken = _manifest(
        key,
        version="2.0.0",
        spec={"openapi": "3.0.3", "info": {"title": "No Server", "version": "1"}, "paths": {}},
        template={
            "name": template_name,
            "description": "version two",
            "workflow_data": WORKFLOW,
        },
    )
    try:
        installed = client.post(
            "/api/connector-packs/install",
            json={"manifest": v1},
            headers=headers,
        )
        assert installed.status_code == 200, installed.text
        failed = client.post(
            f"/api/connector-packs/{key}/upgrade",
            json={"manifest": broken},
            headers=headers,
        )
        assert failed.status_code == 400, failed.text

        definition = get_registry().get_definition(key)
        assert definition is not None
        assert len(definition.operations) == 1

        db = get_session()
        try:
            pack = db.scalar(select(ConnectorPack).where(ConnectorPack.connector_key == key))
            assert pack is not None
            assert pack.version == "1.0.0"
            template = db.scalar(
                select(WorkflowTemplate).where(WorkflowTemplate.name == template_name)
            )
            assert template is not None
            assert template.description == "version one"
        finally:
            db.close()

        generated = (
            Path(__file__).resolve().parent.parent.parent
            / "app"
            / "connectors"
            / "generated"
        )
        assert (generated / f"gen_{key}_connector.py").exists()
    finally:
        _cleanup(key)


def test_uninstall_blocked_by_active_workflow_then_succeeds(client):
    admin = register(client, "pack-uninstall@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    template_name = f"Uninstall Template {key}"
    workflow_id = f"wf_{key}"
    manifest = _manifest(key, template={
        "name": template_name,
        "workflow_data": WORKFLOW,
    })
    try:
        installed = client.post(
            "/api/connector-packs/install",
            json={"manifest": manifest},
            headers=headers,
        )
        assert installed.status_code == 200, installed.text

        workflow = {
            "id": workflow_id,
            "name": "Uses connector pack",
            "nodes": [
                {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                {"id": "pack", "type": key, "parameters": {}},
            ],
            "connections": [{"source": "trigger", "target": "pack"}],
            "settings": {},
        }
        assert client.post("/api/workflows", json=workflow, headers=headers).status_code == 201
        assert client.patch(
            f"/api/workflows/{workflow_id}/active",
            json={"active": True},
            headers=headers,
        ).status_code == 200

        blocked = client.delete(f"/api/connector-packs/{key}", headers=headers)
        assert blocked.status_code == 409
        assert "Uses connector pack" not in blocked.json()["detail"]
        assert "1 active workflow" in blocked.json()["detail"]

        assert client.patch(
            f"/api/workflows/{workflow_id}/active",
            json={"active": False},
            headers=headers,
        ).status_code == 200
        removed = client.delete(f"/api/connector-packs/{key}", headers=headers)
        assert removed.status_code == 200, removed.text
        assert removed.json()["data"]["uninstalled"] is True
        assert get_registry().get_definition(key) is None

        db = get_session()
        try:
            assert db.scalar(
                select(ConnectorPack).where(ConnectorPack.connector_key == key)
            ) is None
            assert db.scalar(
                select(WorkflowTemplate).where(WorkflowTemplate.name == template_name)
            ) is None
        finally:
            db.close()
        generated = (
            Path(__file__).resolve().parent.parent.parent
            / "app"
            / "connectors"
            / "generated"
        )
        assert not (generated / f"gen_{key}_connector.py").exists()
    finally:
        _cleanup(key)


def _fake_registry_fetch(monkeypatch, payload):
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info) -> None:
            return None

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "app.security.safe_http_client.get_safe_http_client",
        lambda: FakeClient(),
    )


def test_signed_registry_preview(client, monkeypatch):
    admin = register(client, "pack-registry@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    private = _trusted_key(monkeypatch)
    index = {
        "schema_version": 1,
        "name": "Test Registry",
        "issued_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "packs": [{
            "name": "registry_demo",
            "display_name": "Registry Demo",
            "version": "2.0.0",
            "description": "A signed registry entry.",
            "category": "api",
            "manifest_url": "https://packs.example/registry-demo.json",
            "revoked": False,
        }],
    }
    signed = sign_manifest(index, private, KEY_ID)
    _fake_registry_fetch(monkeypatch, signed)

    response = client.post(
        "/api/connector-packs/registry/preview",
        json={"registry_url": "https://packs.example/registry.json"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["registry"] == "Test Registry"
    assert data["signing_key_id"] == KEY_ID
    assert data["packs"][0]["name"] == "registry_demo"
    assert data["packs"][0]["manifest_url"] == "https://packs.example/registry-demo.json"
    assert data["packs"][0]["revoked"] is False


def test_registry_requires_https(client, monkeypatch):
    admin = register(client, "pack-registry-http@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    _trusted_key(monkeypatch)
    response = client.post(
        "/api/connector-packs/registry/preview",
        json={"registry_url": "http://packs.example/registry.json"},
        headers=headers,
    )
    assert response.status_code == 400
    assert "https" in response.json()["detail"].lower()


def test_expired_registry_is_rejected(client, monkeypatch):
    admin = register(client, "pack-registry-expired@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    private = _trusted_key(monkeypatch)
    index = {
        "schema_version": 1,
        "name": "Expired Registry",
        "issued_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
        "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "packs": [],
    }
    _fake_registry_fetch(monkeypatch, sign_manifest(index, private, KEY_ID))
    response = client.post(
        "/api/connector-packs/registry/preview",
        json={"registry_url": "https://packs.example/registry.json"},
        headers=headers,
    )
    assert response.status_code == 400
    assert "expired" in response.json()["detail"].lower()


def test_remote_manifest_requires_freshness(client, monkeypatch):
    admin = register(client, "pack-manifest-stale@example.com", "Password123!")
    private = _trusted_key(monkeypatch)
    key = _key()
    manifest = _signed(_manifest(key), private)
    manifest.pop("issued_at")
    manifest.pop("expires_at")
    _fake_registry_fetch(monkeypatch, manifest)
    response = client.post(
        "/api/connector-packs/install",
        json={"manifest_url": "https://packs.example/pack.json"},
        headers=auth_headers(admin["token"]),
    )
    assert response.status_code == 400
    assert "issued_at" in response.json()["detail"]


def test_manifest_url_requires_https(client):
    admin = register(client, "pack-manifest-http@example.com", "Password123!")
    response = client.post(
        "/api/connector-packs/install",
        json={"manifest_url": "http://packs.example/pack.json"},
        headers=auth_headers(admin["token"]),
    )
    assert response.status_code == 400
    assert "https" in response.json()["detail"].lower()


def test_tampered_registry_is_rejected(client, monkeypatch):
    admin = register(client, "pack-registry-bad@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    private = _trusted_key(monkeypatch)
    index = {
        "schema_version": 1,
        "name": "Test Registry",
        "issued_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "packs": [],
    }
    signed = sign_manifest(index, private, KEY_ID)
    signed["name"] = "Tampered Registry"
    _fake_registry_fetch(monkeypatch, signed)

    response = client.post(
        "/api/connector-packs/registry/preview",
        json={"registry_url": "https://packs.example/registry.json"},
        headers=headers,
    )
    assert response.status_code == 400
    assert "verification failed" in response.json()["detail"].lower()


def test_unsigned_registry_is_rejected(client, monkeypatch):
    admin = register(client, "pack-registry-unsigned@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    _trusted_key(monkeypatch)
    _fake_registry_fetch(monkeypatch, {
        "schema_version": 1,
        "name": "Unsigned Registry",
        "packs": [],
    })
    response = client.post(
        "/api/connector-packs/registry/preview",
        json={"registry_url": "https://packs.example/registry.json"},
        headers=headers,
    )
    assert response.status_code == 400
    assert "signing_key_id" in response.json()["detail"]


def test_revoked_signing_key_is_rejected(client, monkeypatch):
    admin = register(client, "pack-revoked-key@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    private = _trusted_key(monkeypatch, revoked=KEY_ID)
    response = client.post(
        "/api/connector-packs/install",
        json={"manifest": _signed(_manifest(key), private)},
        headers=headers,
    )
    assert response.status_code == 400
    assert "revoked" in response.json()["detail"].lower()
    _cleanup(key)


def test_revoked_installed_signing_key_is_unloaded(client, monkeypatch):
    admin = register(client, "pack-revoked-installed@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    private = _trusted_key(monkeypatch)
    try:
        installed = client.post(
            "/api/connector-packs/install",
            json={"manifest": _signed(_manifest(key), private)},
            headers=headers,
        )
        assert installed.status_code == 200, installed.text
        assert get_registry().get_definition(key) is not None

        monkeypatch.setattr(
            get_settings(), "connector_pack_revoked_keys", KEY_ID
        )
        from app.services.connector_pack_reconciler import reconcile_packs

        reconcile_packs(force=True)
        assert get_registry().get_definition(key) is None
        listed = client.get("/api/connector-packs", headers=headers)
        assert listed.json()["data"][0]["revoked"] is True
    finally:
        _cleanup(key)


def test_reconciler_propagates_uninstall(client):
    admin = register(client, "pack-reconcile-uninstall@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    try:
        installed = client.post(
            "/api/connector-packs/install",
            json={"manifest": _manifest(key)},
            headers=headers,
        )
        assert installed.status_code == 200, installed.text
        stale_sources = _read_sources(key)
        assert client.delete(f"/api/connector-packs/{key}", headers=headers).status_code == 200

        # Simulate a worker that missed the uninstall.
        _restore_stale_sources(key, stale_sources)
        assert get_registry().get_definition(key) is not None

        from app.services.connector_pack_reconciler import reconcile_packs

        result = reconcile_packs()
        assert result["unregistered"] >= 1
        assert get_registry().get_definition(key) is None
        assert not (_generated_path(key) / f"gen_{key}_connector.py").exists()

        db = get_session()
        try:
            assert db.scalar(
                select(ConnectorPackTombstone).where(
                    ConnectorPackTombstone.connector_key == key
                )
            ) is not None
        finally:
            db.close()
    finally:
        _cleanup(key)


def test_reconciler_propagates_upgrade(client):
    admin = register(client, "pack-reconcile-upgrade@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    v1 = _manifest(key, version="1.0.0")
    v2 = _manifest(key, version="2.0.0", spec=SPEC_V2)
    try:
        assert client.post(
            "/api/connector-packs/install",
            json={"manifest": v1},
            headers=headers,
        ).status_code == 200
        stale_sources = _read_sources(key)
        assert client.post(
            f"/api/connector-packs/{key}/upgrade",
            json={"manifest": v2},
            headers=headers,
        ).status_code == 200

        # Simulate a worker still holding v1.
        _restore_stale_sources(key, stale_sources)
        assert len(get_registry().get_definition(key).operations) == 1

        from app.services.connector_pack_reconciler import reconcile_packs

        reconcile_packs(force=True)
        definition = get_registry().get_definition(key)
        assert definition is not None
        assert len(definition.operations) == 2
    finally:
        _cleanup(key)


def test_reinstall_after_uninstall_clears_tombstone(client):
    admin = register(client, "pack-reinstall@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    key = _key()
    manifest = _manifest(key)
    try:
        assert client.post(
            "/api/connector-packs/install",
            json={"manifest": manifest},
            headers=headers,
        ).status_code == 200
        assert client.delete(f"/api/connector-packs/{key}", headers=headers).status_code == 200
        reinstalled = client.post(
            "/api/connector-packs/install",
            json={"manifest": manifest},
            headers=headers,
        )
        assert reinstalled.status_code == 200, reinstalled.text
        db = get_session()
        try:
            assert db.scalar(
                select(ConnectorPackTombstone).where(
                    ConnectorPackTombstone.connector_key == key
                )
            ) is None
            assert db.scalar(
                select(ConnectorPack).where(ConnectorPack.connector_key == key)
            ) is not None
        finally:
            db.close()
    finally:
        _cleanup(key)


def test_pack_dependencies_are_enforced(client):
    admin = register(client, "pack-deps@example.com", "Password123!")
    headers = auth_headers(admin["token"])
    dependency = _key()
    dependent = _key()
    dependent_manifest = _manifest(dependent)
    dependent_manifest["requires"] = [dependency]
    try:
        missing = client.post(
            "/api/connector-packs/install",
            json={"manifest": dependent_manifest},
            headers=headers,
        )
        assert missing.status_code == 409
        assert dependency in missing.json()["detail"]

        assert client.post(
            "/api/connector-packs/install",
            json={"manifest": _manifest(dependency)},
            headers=headers,
        ).status_code == 200
        assert client.post(
            "/api/connector-packs/install",
            json={"manifest": dependent_manifest},
            headers=headers,
        ).status_code == 200

        blocked = client.delete(f"/api/connector-packs/{dependency}", headers=headers)
        assert blocked.status_code == 409
        assert dependent in blocked.json()["detail"]

        assert client.delete(f"/api/connector-packs/{dependent}", headers=headers).status_code == 200
        assert client.delete(f"/api/connector-packs/{dependency}", headers=headers).status_code == 200
    finally:
        _cleanup(dependent)
        _cleanup(dependency)


def test_pack_requires_spec(client):
    admin = register(client, "pack-nospec@example.com", "Password123!")
    response = client.post(
        "/api/connector-packs/install",
        json={"manifest": {"name": _key(), "display_name": "Missing spec"}},
        headers=auth_headers(admin["token"]),
    )
    assert response.status_code == 400


def _direct_pack(db, key: str, installed_by: int, *, source_url: str | None = None) -> None:
    db.add(ConnectorPack(
        connector_key=key,
        name=key,
        display_name=key,
        version="1.0.0",
        description="",
        category="api",
        source_url=source_url,
        generated_sources={},
        dependencies=[],
        signed=False,
        installed_by=installed_by,
    ))


def test_pack_uninstall_does_not_disclose_other_tenant_workflow_names(client):
    admin = register(client, "pack-tenant-admin@example.com", "Password123!")
    other = register(client, "pack-tenant-other@example.com", "Password123!")
    key = _key()
    db = get_session()
    try:
        admin_row = db.scalar(select(User).where(User.email == "pack-tenant-admin@example.com"))
        other_row = db.scalar(select(User).where(User.email == "pack-tenant-other@example.com"))
        assert admin_row is not None and other_row is not None
        _direct_pack(db, key, admin_row.id)
        db.add(WorkflowRecord(
            id="wf_other_tenant_secret",
            user_id=other_row.id,
            name="Confidential M&A Migration",
            version=1,
            active=True,
            data={"nodes": [{"id": "n", "type": key, "parameters": {}}]},
        ))
        db.commit()
    finally:
        db.close()

    blocked = client.delete(
        f"/api/connector-packs/{key}", headers=auth_headers(admin["token"])
    )
    assert blocked.status_code == 409
    assert "Confidential M&A Migration" not in blocked.text
    assert "1 active workflow" in blocked.json()["detail"]


def test_pack_list_hides_source_url_from_non_admins(client):
    admin = register(client, "pack-source-admin@example.com", "Password123!")
    member = register(client, "pack-source-member@example.com", "Password123!")
    key = _key()
    db = get_session()
    try:
        admin_row = db.scalar(select(User).where(User.email == "pack-source-admin@example.com"))
        assert admin_row is not None
        _direct_pack(db, key, admin_row.id, source_url="https://user:pass@packs.example/private.json")
        db.commit()
    finally:
        db.close()

    listed = client.get("/api/connector-packs", headers=auth_headers(member["token"]))
    assert listed.status_code == 200
    pack = next(item for item in listed.json()["data"] if item["connector_key"] == key)
    assert pack["source_url"] is None

    admin_listed = client.get("/api/connector-packs", headers=auth_headers(admin["token"]))
    admin_pack = next(item for item in admin_listed.json()["data"] if item["connector_key"] == key)
    assert admin_pack["source_url"] == "https://user:pass@packs.example/private.json"
