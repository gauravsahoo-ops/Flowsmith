"""Admin-only connector/template pack installation and lifecycle.

A pack is a JSON manifest with an OpenAPI/Swagger spec and optional workflow
templates. Remote manifest URLs must carry a valid Ed25519 signature; inline
manifests may also be signed and can be made mandatory in production. The spec
goes through the same generated-connector path as the OpenAPI importer.

This is a local/offline installer and signed distribution foundation, not a
hosted public registry with moderation or package dependency resolution.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok, validate_workflow_payload
from app.audit import log_event
from app.config import get_settings
from app.db import get_db
from app.importexport import sanitize_workflow_data
from app.models import (
    ConnectorPack,
    ConnectorPackTombstone,
    User,
    WorkflowRecord,
    WorkflowTemplate,
)
from app.services.connector_pack_signing import (
    PackSignatureError,
    SignatureInfo,
    manifest_digest,
    parse_trusted_keys,
    sha256_bytes,
    verify_manifest_signature,
)
from app.services.connector_pack_registry import verify_registry_index

logger = logging.getLogger("connector_packs")

router = APIRouter(prefix="/api/connector-packs", tags=["connector-packs"])

MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_TEMPLATES = 50
MAX_DEPENDENCIES = 50
MANIFEST_MAX_LIFETIME = timedelta(days=30)
MANIFEST_CLOCK_SKEW = timedelta(minutes=5)
_SAFE_PACK_KEY = re.compile(r"^[a-z0-9_]+$")


def _require_https_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{label} must use HTTPS.",
        )
    return value


class InstallPackRequest(BaseModel):
    manifest: dict[str, Any] | None = None
    manifest_url: str | None = Field(default=None, max_length=2048)


class RegistryPreviewRequest(BaseModel):
    registry_url: str = Field(min_length=8, max_length=2048)


@dataclass(frozen=True)
class ParsedManifest:
    name: str
    display_name: str
    version: str
    description: str
    category: str
    spec: Any
    base_url: str
    dependencies: tuple[str, ...]
    signature: SignatureInfo | None
    manifest_sha256: str


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin privileges required.")


async def _load_manifest(payload: InstallPackRequest) -> tuple[dict[str, Any], bool]:
    if payload.manifest is not None and payload.manifest_url:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Provide either manifest or manifest_url, not both.",
        )
    remote = False
    if payload.manifest is not None:
        manifest = payload.manifest
    elif payload.manifest_url:
        remote = True
        manifest_url = _require_https_url(payload.manifest_url, "Pack manifest URL")
        from app.security.safe_http_client import get_safe_http_client

        async with get_safe_http_client() as client:
            try:
                response = await client.get(
                    manifest_url,
                    headers={"User-Agent": "Flowsmith-Connector-Pack/1.0"},
                    timeout=30.0,
                    max_response_bytes=MAX_MANIFEST_BYTES,
                )
                response.raise_for_status()
                manifest = response.json()
            except Exception as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Failed to load pack manifest: {exc}",
                ) from exc
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A manifest object or manifest_url is required.",
        )

    if not isinstance(manifest, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pack manifest must be a JSON object.")
    try:
        encoded = json.dumps(manifest).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid pack manifest: {exc}") from exc
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pack manifest is too large.")
    return manifest, remote


def _string_field(
    manifest: dict[str, Any],
    key: str,
    *,
    default: str = "",
    max_length: int = 255,
) -> str:
    value = manifest.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Manifest field '{key}' must be a string.")
    value = value.strip()
    if len(value) > max_length:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Manifest field '{key}' exceeds {max_length} characters.",
        )
    return value


def _trusted_keys():
    try:
        return parse_trusted_keys(get_settings().connector_pack_trusted_keys)
    except PackSignatureError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Connector-pack trust configuration is invalid: {exc}",
        ) from exc


def _revoked_key_ids() -> set[str]:
    raw = get_settings().connector_pack_revoked_keys or ""
    return {part.strip() for part in raw.split(",") if part.strip()}


def _verify_manifest(manifest: dict[str, Any], *, remote: bool) -> SignatureInfo | None:
    signature_present = bool(manifest.get("signature") or manifest.get("signing_key_id"))
    required = remote or get_settings().connector_pack_require_signature
    if not signature_present:
        if required:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "A signed manifest is required for this connector pack.",
            )
        return None

    trusted = _trusted_keys()
    if not trusted:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No trusted connector-pack keys are configured.",
        )
    try:
        return verify_manifest_signature(manifest, trusted, _revoked_key_ids())
    except PackSignatureError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _manifest_timestamp(manifest: dict[str, Any], key: str) -> datetime:
    raw = _string_field(manifest, key, max_length=64)
    if not raw:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Remote pack manifest requires timezone-aware '{key}'.",
        )
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Manifest field '{key}' must be an ISO-8601 timestamp.",
        ) from exc
    if parsed.tzinfo is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Manifest field '{key}' must include a timezone.",
        )
    return parsed.astimezone(UTC)


def _validate_manifest_freshness(manifest: dict[str, Any]) -> None:
    issued_at = _manifest_timestamp(manifest, "issued_at")
    expires_at = _manifest_timestamp(manifest, "expires_at")
    now = datetime.now(UTC)
    if issued_at > now + MANIFEST_CLOCK_SKEW:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Manifest 'issued_at' is in the future.",
        )
    if expires_at <= issued_at:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Manifest 'expires_at' must be after 'issued_at'.",
        )
    if expires_at <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pack manifest has expired.")
    if expires_at - issued_at > MANIFEST_MAX_LIFETIME:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Manifest lifetime may not exceed {MANIFEST_MAX_LIFETIME.days} days.",
        )


def _parse_manifest(manifest: dict[str, Any], *, remote: bool) -> ParsedManifest:
    if remote:
        _validate_manifest_freshness(manifest)
    name = _string_field(manifest, "name", max_length=128)
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Manifest 'name' is required.")
    title = _string_field(manifest, "title")
    display_name = _string_field(manifest, "display_name", default=title, max_length=255)
    version = _string_field(manifest, "version", default="1.0.0", max_length=64)
    description = _string_field(manifest, "description", max_length=5000)
    category = _string_field(manifest, "category", default="api", max_length=64)
    spec = manifest.get("spec") or manifest.get("openapi")
    if not spec:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Manifest requires an OpenAPI 'spec'.")
    base_url = _string_field(manifest, "base_url", max_length=2048)
    raw_dependencies = manifest.get("requires")
    if raw_dependencies is None:
        raw_dependencies = manifest.get("dependencies")
    if raw_dependencies is None:
        raw_dependencies = []
    if not isinstance(raw_dependencies, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Manifest 'requires' must be a list.")
    if len(raw_dependencies) > MAX_DEPENDENCIES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"A pack may declare at most {MAX_DEPENDENCIES} dependencies.",
        )
    from app.connectors.openapi_emit import connector_key_for

    self_key = connector_key_for(name)
    dependencies: list[str] = []
    for item in raw_dependencies:
        if not isinstance(item, str) or not _SAFE_PACK_KEY.fullmatch(item.strip()):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Pack dependencies must be connector keys such as 'postgres'.",
            )
        dependency = item.strip()
        if dependency == self_key:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A pack cannot require itself.")
        if dependency not in dependencies:
            dependencies.append(dependency)
    signature = _verify_manifest(manifest, remote=remote)
    return ParsedManifest(
        name=name,
        display_name=display_name,
        version=version,
        description=description,
        category=category,
        spec=spec,
        base_url=base_url,
        dependencies=tuple(dependencies),
        signature=signature,
        manifest_sha256=signature.sha256 if signature else manifest_digest(manifest),
    )


def _is_url(value: Any) -> bool:
    return isinstance(value, str) and value.strip().startswith(("http://", "https://"))


async def _resolve_spec(
    spec: Any,
    manifest: dict[str, Any],
    *,
    signed: bool,
    remote: bool,
) -> Any:
    """Fetch URL specs once and verify a signed spec_sha256 when required.

    A signature over a manifest that only contains a spec URL authenticates the
    URL, not the bytes served by it. Signed/remote manifests therefore must
    include ``spec_sha256`` for URL specs, and we pass the verified bytes to the
    importer so it cannot refetch different content.
    """
    if not _is_url(spec):
        return spec
    if (signed or remote) and str(spec).strip().lower().startswith("http://"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Signed or remote pack specs must use HTTPS.",
        )

    from app.api.connectors import _load_source_text

    try:
        loaded = await _load_source_text(spec)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Failed to load OpenAPI spec: {exc}",
        ) from exc
    if isinstance(loaded, str):
        material = loaded.encode("utf-8")
    else:
        material = json.dumps(loaded, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = sha256_bytes(material)

    expected = manifest.get("spec_sha256")
    if signed or remote:
        if not isinstance(expected, str) or len(expected.strip()) != 64:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Signed manifests with a spec URL require a 64-character spec_sha256.",
            )
        if not hmac.compare_digest(expected.strip().lower(), digest):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "OpenAPI spec SHA-256 does not match spec_sha256.",
            )
    return loaded


def _template_rows(
    db: Session,
    manifest: dict[str, Any],
    user: User,
    *,
    pack_key: str,
    allow_existing_pack_key: str | None = None,
) -> list[WorkflowTemplate]:
    raw_templates = manifest.get("templates") or []
    if not isinstance(raw_templates, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Manifest 'templates' must be a list.")
    if len(raw_templates) > MAX_TEMPLATES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"A pack may contain at most {MAX_TEMPLATES} templates.",
        )

    from app.api.environments import _DEFAULT_TEMPLATE_NAMES

    allowed_existing: set[str] = set()
    if allow_existing_pack_key:
        allowed_existing = set(db.scalars(
            select(WorkflowTemplate.name).where(
                WorkflowTemplate.pack_key == allow_existing_pack_key
            )
        ).all())

    rows: list[WorkflowTemplate] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_templates):
        if not isinstance(raw, dict):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Template at index {index} must be an object.",
            )
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Template at index {index} requires a name.",
            )
        name = name.strip()
        if len(name) > 255:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Template name is too long.")
        if name in seen or name in _DEFAULT_TEMPLATE_NAMES:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Template name '{name}' is already reserved or duplicated.",
            )
        existing = db.scalar(select(WorkflowTemplate.id).where(WorkflowTemplate.name == name))
        if existing is not None and name not in allowed_existing:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Template name '{name}' already exists.",
            )
        seen.add(name)

        workflow_data = raw.get("workflow_data")
        if not isinstance(workflow_data, dict):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Template '{name}' requires a workflow_data object.",
            )
        try:
            validate_workflow_payload(workflow_data)
        except HTTPException as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Template '{name}' is invalid: {exc.detail}",
            ) from exc

        description = raw.get("description") or ""
        category = raw.get("category") or "general"
        if not isinstance(description, str) or not isinstance(category, str):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Template '{name}' description/category must be strings.",
            )

        rows.append(WorkflowTemplate(
            name=name,
            description=description[:5000],
            category=category[:100],
            workflow_data=json.dumps(
                sanitize_workflow_data(
                    workflow_data,
                    strip_credentials=True,
                    strip_secrets=True,
                )
            ),
            pack_key=pack_key,
            is_public=True,
            created_by=user.id,
        ))
    return rows


def _generated_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "connectors" / "generated"


def _required_sources(connector_key: str) -> list[str]:
    return [f"gen_{connector_key}_{suffix}.py" for suffix in ("provider", "definition", "connector")]


def _read_generated_sources(connector_key: str) -> dict[str, str]:
    sources: dict[str, str] = {}
    for filename in _required_sources(connector_key):
        path = _generated_dir() / filename
        if not path.is_file():
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Generated connector files were not written.",
            )
        sources[filename] = path.read_text(encoding="utf-8")
    return sources


def _write_generated_sources(connector_key: str, sources: dict[str, str]) -> None:
    generated_dir = _generated_dir()
    generated_dir.mkdir(parents=True, exist_ok=True)
    for filename in _required_sources(connector_key):
        source = sources.get(filename)
        if not isinstance(source, str):
            raise OSError(f"Missing generated source {filename}")
        (generated_dir / filename).write_text(source, encoding="utf-8")


def _restore_generated(connector_key: str, sources: dict[str, str]) -> None:
    try:
        _write_generated_sources(connector_key, sources)
        from app.connectors import get_registry
        from app.connectors.openapi_emit import invalidate_generated_modules, register_generated

        invalidate_generated_modules(connector_key)
        register_generated(get_registry(), str(_generated_dir()))
    except Exception:
        logger.exception("could not restore connector pack %s after a failed operation", connector_key)


def _cleanup_generated(connector_key: str) -> None:
    """Remove a generated connector triple and unregister it."""
    generated_dir = _generated_dir()
    for filename in _required_sources(connector_key):
        try:
            (generated_dir / filename).unlink(missing_ok=True)
        except OSError:
            logger.exception("could not remove generated file %s", filename)
    try:
        from app.connectors import get_registry

        get_registry().unregister(connector_key)
    except Exception:
        logger.exception("could not unregister generated connector %s", connector_key)
    try:
        from app.connectors.openapi_emit import invalidate_generated_modules

        invalidate_generated_modules(connector_key)
    except Exception:
        logger.exception("could not invalidate generated modules for %s", connector_key)


def _advisory_lock(db: Session, connector_key: str) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    lock_id = int.from_bytes(
        hashlib.sha256(connector_key.encode("utf-8")).digest()[:8], "big", signed=True
    )
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})


def _active_workflow_count(db: Session, connector_key: str) -> int:
    rows = db.execute(
        select(WorkflowRecord).where(
            WorkflowRecord.active.is_(True),
            WorkflowRecord.deleted_at.is_(None),
        )
    ).scalars().all()
    count = 0
    for record in rows:
        data = record.data or {}
        nodes = data.get("nodes") if isinstance(data, dict) else None
        if not isinstance(nodes, list):
            continue
        if any(
            isinstance(node, dict) and node.get("type") == connector_key
            for node in nodes
        ):
            count += 1
    return count


async def _generate_connector(
    parsed: ParsedManifest,
    spec: Any,
    user: User,
) -> tuple[dict[str, Any], str, dict[str, str]]:
    from app.api.connectors import ImportOpenApiRequest, import_openapi

    response = await import_openapi(
        ImportOpenApiRequest(
            spec=spec,
            name=parsed.name,
            title=parsed.display_name,
            category=parsed.category,
            base_url=parsed.base_url,
        ),
        user,
    )
    imported = response.get("data") or response
    connector_key = str(imported.get("connector_key") or "")
    if not connector_key:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Importer returned no connector key.")
    return imported, connector_key, _read_generated_sources(connector_key)


def _require_dependencies(db: Session, dependencies: tuple[str, ...]) -> None:
    if not dependencies:
        return
    installed = set(db.scalars(select(ConnectorPack.connector_key)).all())
    missing = [dependency for dependency in dependencies if dependency not in installed]
    if missing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Pack requires installed pack(s): " + ", ".join(missing),
        )


def _pack_values(parsed: ParsedManifest, imported: dict[str, Any], key: str, user: User) -> dict[str, Any]:
    return {
        "connector_key": key,
        "name": parsed.name,
        "display_name": str(imported.get("display_name") or parsed.display_name or parsed.name),
        "version": parsed.version,
        "description": parsed.description,
        "category": parsed.category,
        "dependencies": list(parsed.dependencies),
        "signed": parsed.signature is not None,
        "signing_key_id": parsed.signature.key_id if parsed.signature else None,
        "manifest_sha256": parsed.manifest_sha256,
    }


@router.get("")
def list_connector_packs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """List installed connector packs (authenticated read access)."""
    packs = db.execute(
        select(ConnectorPack).order_by(ConnectorPack.created_at.desc())
    ).scalars().all()
    revoked_keys = _revoked_key_ids()
    return ok([
        {
            "connector_key": pack.connector_key,
            "name": pack.name,
            "display_name": pack.display_name,
            "version": pack.version,
            "description": pack.description,
            "category": pack.category,
            "source_url": pack.source_url if user.role == "admin" else None,
            "template_count": pack.template_count,
            "dependencies": list(pack.dependencies or []),
            "signed": pack.signed,
            "signing_key_id": pack.signing_key_id,
            "revoked": bool(
                pack.signing_key_id and pack.signing_key_id in revoked_keys
            ),
            "manifest_sha256": pack.manifest_sha256,
            "installed_by": pack.installed_by,
            "created_at": str(pack.created_at),
            "updated_at": str(pack.updated_at),
        }
        for pack in packs
    ])


@router.post("/registry/preview")
async def preview_connector_registry(
    body: RegistryPreviewRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Fetch and verify a signed registry index without installing anything."""
    _require_admin(user)
    trusted = _trusted_keys()
    if not trusted:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No trusted connector-pack keys are configured.",
        )

    registry_url = _require_https_url(body.registry_url, "Connector registry URL")
    from app.security.safe_http_client import get_safe_http_client

    async with get_safe_http_client() as client:
        try:
            response = await client.get(
                registry_url,
                headers={"User-Agent": "Flowsmith-Connector-Registry/1.0"},
                timeout=30.0,
                max_response_bytes=MAX_MANIFEST_BYTES,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Failed to load connector registry: {exc}",
            ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Registry index must be a JSON object.")
    try:
        index = verify_registry_index(payload, trusted, _revoked_key_ids())
    except PackSignatureError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return ok({
        "registry": index.name,
        "signing_key_id": index.signature.key_id,
        "manifest_sha256": index.signature.sha256,
        "packs": [
            {
                "name": pack.name,
                "display_name": pack.display_name,
                "version": pack.version,
                "description": pack.description,
                "category": pack.category,
                "manifest_url": pack.manifest_url,
                "revoked": pack.revoked,
            }
            for pack in index.packages
        ],
    })


@router.post("/install")
async def install_connector_pack(
    body: InstallPackRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Install an admin-supplied connector pack."""
    _require_admin(user)
    manifest, remote = await _load_manifest(body)
    parsed = _parse_manifest(manifest, remote=remote)
    spec = await _resolve_spec(
        parsed.spec, manifest, signed=parsed.signature is not None, remote=remote
    )

    from app.connectors import ensure_builtin_connectors, get_registry
    from app.connectors.openapi_emit import connector_key_for
    from app.services.connector_pack_runtime import clear_pack_cache

    connector_key = connector_key_for(parsed.name)
    _advisory_lock(db, connector_key)
    existing_pack = db.scalar(
        select(ConnectorPack).where(ConnectorPack.connector_key == connector_key)
    )
    if existing_pack is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Connector pack '{connector_key}' is already installed.",
        )
    ensure_builtin_connectors()
    if get_registry().get_definition(connector_key) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Connector key '{connector_key}' is already registered. Choose another name.",
        )
    _require_dependencies(db, parsed.dependencies)
    db.execute(
        delete(ConnectorPackTombstone).where(
            ConnectorPackTombstone.connector_key == connector_key
        )
    )

    imported: dict[str, Any] | None = None
    try:
        imported, generated_key, generated_sources = await _generate_connector(parsed, spec, user)
        if generated_key != connector_key:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Manifest name produced an unexpected connector key.",
            )
        templates = _template_rows(db, manifest, user, pack_key=connector_key)
        values = _pack_values(parsed, imported, connector_key, user)
        pack = ConnectorPack(
            **values,
            source_url=body.manifest_url,
            template_count=len(templates),
            generated_sources=generated_sources,
            installed_by=user.id,
        )
        db.add(pack)
        for template in templates:
            db.add(template)
        db.flush()
        template_refs = [{"id": template.id, "name": template.name} for template in templates]
        pack_display_name = pack.display_name
        db.commit()
    except Exception:
        db.rollback()
        _cleanup_generated(connector_key)
        raise

    clear_pack_cache(connector_key)
    log_event(
        db,
        "connector_pack.installed",
        target_type="connector_pack",
        target_id=connector_key,
        user_id=user.id,
        detail={
            "version": parsed.version,
            "template_count": len(template_refs),
            "operations_count": imported.get("operations_count"),
            "signed": parsed.signature is not None,
            "signing_key_id": parsed.signature.key_id if parsed.signature else None,
        },
    )
    return ok({
        "connector_key": connector_key,
        "display_name": pack_display_name,
        "version": parsed.version,
        "operations_count": imported.get("operations_count"),
        "templates": template_refs,
        "template_count": len(template_refs),
        "dependencies": list(parsed.dependencies),
        "signed": parsed.signature is not None,
        "signing_key_id": parsed.signature.key_id if parsed.signature else None,
        "manifest_sha256": parsed.manifest_sha256,
    })


@router.post("/{connector_key}/upgrade")
async def upgrade_connector_pack(
    connector_key: str,
    body: InstallPackRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Upgrade an installed pack from a signed/inline manifest."""
    _require_admin(user)
    manifest, remote = await _load_manifest(body)
    parsed = _parse_manifest(manifest, remote=remote)

    from app.connectors.openapi_emit import connector_key_for
    from app.services.connector_pack_runtime import clear_pack_cache

    if connector_key_for(parsed.name) != connector_key:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Manifest name does not match the pack being upgraded.",
        )
    _advisory_lock(db, connector_key)
    pack = db.scalar(
        select(ConnectorPack).where(ConnectorPack.connector_key == connector_key)
    )
    if pack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connector pack not found.")
    _require_dependencies(db, parsed.dependencies)
    db.execute(
        delete(ConnectorPackTombstone).where(
            ConnectorPackTombstone.connector_key == connector_key
        )
    )
    try:
        if Version(parsed.version) <= Version(pack.version):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"New version {parsed.version} must be greater than installed version {pack.version}.",
            )
    except InvalidVersion as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Pack versions must be valid PEP 440 versions.",
        ) from exc

    templates = _template_rows(
        db,
        manifest,
        user,
        pack_key=connector_key,
        allow_existing_pack_key=connector_key,
    )
    spec = await _resolve_spec(
        parsed.spec, manifest, signed=parsed.signature is not None, remote=remote
    )
    old_sources = dict(pack.generated_sources or {})
    imported: dict[str, Any] | None = None

    try:
        _cleanup_generated(connector_key)
        imported, generated_key, generated_sources = await _generate_connector(parsed, spec, user)
        if generated_key != connector_key:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Manifest name produced an unexpected connector key.",
            )
        values = _pack_values(parsed, imported, connector_key, user)
        for field, value in values.items():
            setattr(pack, field, value)
        pack.source_url = body.manifest_url
        pack.template_count = len(templates)
        pack.generated_sources = generated_sources
        pack.updated_at = datetime.now(UTC)
        db.execute(
            delete(WorkflowTemplate).where(WorkflowTemplate.pack_key == connector_key)
        )
        for template in templates:
            db.add(template)
        db.flush()
        template_refs = [{"id": template.id, "name": template.name} for template in templates]
        pack_display_name = pack.display_name
        db.commit()
    except Exception:
        db.rollback()
        _cleanup_generated(connector_key)
        _restore_generated(connector_key, old_sources)
        raise

    clear_pack_cache(connector_key)
    log_event(
        db,
        "connector_pack.upgraded",
        target_type="connector_pack",
        target_id=connector_key,
        user_id=user.id,
        detail={
            "version": parsed.version,
            "template_count": len(template_refs),
            "signed": parsed.signature is not None,
            "signing_key_id": parsed.signature.key_id if parsed.signature else None,
        },
    )
    return ok({
        "connector_key": connector_key,
        "display_name": pack_display_name,
        "version": parsed.version,
        "operations_count": imported.get("operations_count"),
        "templates": template_refs,
        "template_count": len(template_refs),
        "dependencies": list(parsed.dependencies),
        "signed": parsed.signature is not None,
        "signing_key_id": parsed.signature.key_id if parsed.signature else None,
        "manifest_sha256": parsed.manifest_sha256,
    })


@router.delete("/{connector_key}")
def uninstall_connector_pack(
    connector_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Uninstall a generated pack and its pack-owned templates."""
    _require_admin(user)
    _advisory_lock(db, connector_key)
    pack = db.scalar(
        select(ConnectorPack).where(ConnectorPack.connector_key == connector_key)
    )
    if pack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connector pack not found.")

    active_count = _active_workflow_count(db, connector_key)
    if active_count:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Pack is used by {active_count} active workflow(s). "
            "Deactivate or remove them before uninstalling.",
        )
    dependent_packs = [
        other.connector_key
        for other in db.execute(
            select(ConnectorPack).where(ConnectorPack.connector_key != connector_key)
        ).scalars().all()
        if connector_key in (other.dependencies or [])
    ]
    if dependent_packs:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Pack is required by installed pack(s): " + ", ".join(dependent_packs),
        )

    old_sources = dict(pack.generated_sources or {})
    _cleanup_generated(connector_key)
    try:
        db.execute(
            delete(WorkflowTemplate).where(WorkflowTemplate.pack_key == connector_key)
        )
        db.add(ConnectorPackTombstone(connector_key=connector_key))
        db.delete(pack)
        db.commit()
    except Exception:
        db.rollback()
        _restore_generated(connector_key, old_sources)
        raise

    from app.services.connector_pack_runtime import clear_pack_cache

    clear_pack_cache(connector_key)
    log_event(
        db,
        "connector_pack.uninstalled",
        target_type="connector_pack",
        target_id=connector_key,
        user_id=user.id,
    )
    return ok({"connector_key": connector_key, "uninstalled": True})
