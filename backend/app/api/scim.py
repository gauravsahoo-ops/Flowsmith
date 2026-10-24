"""SCIM 2.0 user and group provisioning.

Users support discovery, create, read, replace, patch, and deprovision (soft
delete). Groups are mapped to private workspaces and synchronized through the
separate ``scim_groups`` router.

Authentication is a dedicated bearer token, separate from user JWTs. The
endpoint is disabled unless ``SCIM_ENABLED=true`` and a token is configured.
"""

from __future__ import annotations

import hmac
import re
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import REGISTER, USER_ROLE_CHANGE, USER_STATE_CHANGE, log_event
from app.config import get_settings
from app.db import get_db
from app.models import ScimGroup, ScimGroupAccess, User
from app.security.jwt import hash_password
from app.services.user_provisioning import apply_default_scope

router = APIRouter(prefix="/scim/v2", tags=["scim"])

_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
_GROUP_EXTENSION_SCHEMA = "urn:flowsmith:params:scim:schemas:extension:group:2.0:Group"
_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
_FILTER_RE = re.compile(
    r'^\s*(userName|emails\.value|externalId|id|active)\s+eq\s+(?:"([^"]*)"|([^\s]+))\s*$',
    re.IGNORECASE,
)
_MAX_RESULTS = 200


def _scim_json(payload: Any, status_code: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/scim+json",
        headers=headers,
    )


def _scim_error(status_code: int, detail: str) -> JSONResponse:
    return _scim_json(
        {
            "schemas": [_ERROR_SCHEMA],
            "detail": detail,
            "status": str(status_code),
        },
        status_code=status_code,
    )


def _require_scim(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    settings = get_settings()
    expected = (settings.scim_bearer_token or "").strip()
    if not settings.scim_enabled or not expected:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SCIM is not enabled.")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "SCIM bearer token is required.",
            headers={"WWW-Authenticate": 'Bearer realm="SCIM"'},
        )
    provided = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid SCIM bearer token.",
            headers={"WWW-Authenticate": 'Bearer realm="SCIM"'},
        )


def _base_url(request: Request) -> str:
    settings = get_settings()
    configured = (settings.public_url or "").strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def _resource_meta(request: Request, resource_type: str, resource_id: str) -> dict[str, Any]:
    location = f"{_base_url(request)}/scim/v2/{resource_type}/{resource_id}"
    return {"resourceType": resource_type, "location": location}


def _role_from_body(body: dict[str, Any]) -> str:
    roles = body.get("roles")
    if isinstance(roles, list):
        for role in roles:
            value = role.get("value") if isinstance(role, dict) else role
            normalized = str(value or "").strip().lower()
            if normalized in ("admin", "member", "owner"):
                return "admin" if normalized == "owner" else normalized
    return "member"


def _email_from_body(body: dict[str, Any]) -> str:
    raw = body.get("userName")
    if not raw:
        emails = body.get("emails")
        if isinstance(emails, list) and emails and isinstance(emails[0], dict):
            raw = emails[0].get("value")
    email = str(raw or "").strip().lower()
    if not email or "@" not in email or any(ch.isspace() for ch in email):
        raise ValueError("A valid userName (email address) is required.")
    return email


def _groups_for_user(db: Session, user: User) -> list[dict[str, str]]:
    groups = db.execute(
        select(ScimGroup)
        .join(ScimGroupAccess, ScimGroupAccess.group_id == ScimGroup.id)
        .where(
            ScimGroupAccess.user_id == user.id,
            ScimGroup.active.is_(True),
        )
        .order_by(ScimGroup.id)
    ).scalars().all()
    return [{"value": group.id, "display": group.display_name} for group in groups]


def _user_resource(
    db: Session, user: User, request: Request, *, include_groups: bool = True
) -> dict[str, Any]:
    created = user.created_at.isoformat() if user.created_at else None
    resource: dict[str, Any] = {
        "schemas": [_USER_SCHEMA],
        "id": str(user.id),
        "userName": user.email,
        "name": {"formatted": user.email},
        "displayName": user.email,
        "emails": [{"value": user.email, "primary": True, "type": "work"}],
        "active": bool(user.active),
        "roles": [{"value": user.role, "primary": True, "type": "work"}],
        "meta": {
            **_resource_meta(request, "Users", str(user.id)),
            "created": created,
            "lastModified": created,
        },
    }
    if include_groups:
        groups = _groups_for_user(db, user)
        if groups:
            resource["groups"] = groups
    return resource


def _get_user(db: Session, user_id: str) -> User | None:
    try:
        return db.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def _unique_email(db: Session, email: str, *, exclude_id: int | None = None) -> bool:
    existing = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    return existing is None or existing.id == exclude_id


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("A user with that userName already exists.") from exc


def _filtered_users(db: Session, filter_value: str | None) -> list[User]:
    if not filter_value:
        return list(db.execute(select(User).order_by(User.id)).scalars().all())
    match = _FILTER_RE.match(filter_value)
    if not match:
        raise ValueError("Unsupported SCIM filter. Supported: userName, emails.value, active, id.")
    field, quoted, bare = match.groups()
    value = (quoted if quoted is not None else bare).strip()
    field = field.lower()
    if field == "active":
        active = value.lower() == "true"
        return list(db.execute(
            select(User).where(User.active == active).order_by(User.id)
        ).scalars().all())
    if field == "id":
        try:
            user = db.get(User, int(value))
        except ValueError:
            return []
        return [user] if user else []
    if field == "username" or field == "emails.value":
        user = db.scalar(select(User).where(func.lower(User.email) == value.lower()))
        return [user] if user else []
    return []


@router.get("/ServiceProviderConfig")
def service_provider_config(request: Request, _: None = Depends(_require_scim)) -> JSONResponse:
    return _scim_json({
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": f"{_base_url(request)}/scim/v2",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": _MAX_RESULTS},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [{
            "type": "oauthbearertoken",
            "name": "OAuth Bearer Token",
            "description": "Dedicated SCIM provisioning token.",
            "primary": True,
        }],
    })


@router.get("/ResourceTypes")
def resource_types(request: Request, _: None = Depends(_require_scim)) -> JSONResponse:
    return _scim_json({
        "schemas": [_LIST_SCHEMA],
        "totalResults": 2,
        "startIndex": 1,
        "itemsPerPage": 2,
        "Resources": [
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
                "id": "User",
                "name": "User",
                "endpoint": "/Users",
                "schema": _USER_SCHEMA,
                "meta": {"location": f"{_base_url(request)}/scim/v2/ResourceTypes/User"},
            },
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
                "id": "Group",
                "name": "Group",
                "endpoint": "/Groups",
                "schema": _GROUP_SCHEMA,
                "meta": {"location": f"{_base_url(request)}/scim/v2/ResourceTypes/Group"},
            },
        ],
    })


@router.get("/Schemas")
def schemas(request: Request, _: None = Depends(_require_scim)) -> JSONResponse:
    return _scim_json({
        "schemas": [_LIST_SCHEMA],
        "totalResults": 3,
        "startIndex": 1,
        "itemsPerPage": 3,
        "Resources": [
            {
                "id": _USER_SCHEMA,
                "name": "User",
                "description": "Flowsmith user account",
                "attributes": [
                    {"name": "userName", "type": "string", "multiValued": False, "required": True, "uniqueness": "server"},
                    {"name": "active", "type": "boolean", "multiValued": False, "required": False},
                    {"name": "roles", "type": "complex", "multiValued": True, "required": False},
                    {"name": "emails", "type": "complex", "multiValued": True, "required": False},
                    {"name": "name", "type": "complex", "multiValued": False, "required": False},
                ],
                "meta": {"resourceType": "Schema", "location": f"{_base_url(request)}/scim/v2/Schemas/{_USER_SCHEMA}"},
            },
            {
                "id": _GROUP_SCHEMA,
                "name": "Group",
                "description": "Flowsmith workspace-backed group",
                "attributes": [
                    {"name": "displayName", "type": "string", "multiValued": False, "required": True, "uniqueness": "server"},
                    {"name": "externalId", "type": "string", "multiValued": False, "required": False},
                    {"name": "members", "type": "complex", "multiValued": True, "required": False},
                ],
                "meta": {"resourceType": "Schema", "location": f"{_base_url(request)}/scim/v2/Schemas/{_GROUP_SCHEMA}"},
            },
            {
                "id": _GROUP_EXTENSION_SCHEMA,
                "name": "FlowsmithGroupExtension",
                "description": "Optional organization role granted to group members",
                "attributes": [
                    {"name": "organizationRole", "type": "string", "multiValued": False, "required": False,
                     "canonicalValues": ["admin", "member"]},
                    {"name": "organizationPermission", "type": "string", "multiValued": False, "required": False,
                     "canonicalValues": ["view", "edit", "admin"]},
                ],
                "meta": {"resourceType": "Schema",
                         "location": f"{_base_url(request)}/scim/v2/Schemas/{_GROUP_EXTENSION_SCHEMA}"},
            },
        ],
    })


@router.get("/Users")
def list_users(
    request: Request,
    filter: str | None = Query(default=None),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=0, le=_MAX_RESULTS),
    _: None = Depends(_require_scim),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        users = _filtered_users(db, filter)
    except ValueError as exc:
        return _scim_error(400, str(exc))
    total = len(users)
    page = users[startIndex - 1:startIndex - 1 + count] if count else []
    return _scim_json({
        "schemas": [_LIST_SCHEMA],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(page),
        "Resources": [_user_resource(db, user, request) for user in page],
    })


@router.post("/Users", status_code=status.HTTP_201_CREATED)
def create_user(
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(_require_scim),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        email = _email_from_body(body)
        if not _unique_email(db, email):
            return _scim_error(409, "A user with that userName already exists.")
        settings = get_settings()
        user = User(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            role=_role_from_body(body),
            active=bool(body.get("active", True)),
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return _scim_error(409, "A user with that userName already exists.")
        apply_default_scope(
            db, user,
            settings.scim_default_organization_id,
            settings.scim_default_workspace_id,
        )
        _commit(db)
        db.refresh(user)
        log_event(db, REGISTER, target_type="user", target_id=str(user.id), user_id=user.id,
                  detail={"source": "scim"})
        resource = _user_resource(db, user, request)
        return _scim_json(
            resource, status.HTTP_201_CREATED,
            headers={"Location": resource["meta"]["location"]},
        )
    except ValueError as exc:
        db.rollback()
        return _scim_error(400, str(exc))


@router.get("/Users/{user_id}")
def get_user(
    user_id: str,
    request: Request,
    _: None = Depends(_require_scim),
    db: Session = Depends(get_db),
) -> JSONResponse:
    user = _get_user(db, user_id)
    if user is None:
        return _scim_error(404, "User not found.")
    return _scim_json(_user_resource(db, user, request))


@router.put("/Users/{user_id}")
def replace_user(
    user_id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(_require_scim),
    db: Session = Depends(get_db),
) -> JSONResponse:
    user = _get_user(db, user_id)
    if user is None:
        return _scim_error(404, "User not found.")
    try:
        email = _email_from_body(body)
        if not _unique_email(db, email, exclude_id=user.id):
            return _scim_error(409, "A user with that userName already exists.")
        role = _role_from_body(body)
        active = bool(body.get("active", True))
        old_role = user.role
        old_active = user.active
        user.email = email
        user.role = role
        user.active = active
        if not active:
            user.tokens_valid_from = datetime.now(UTC)
        _commit(db)
        db.refresh(user)
        if old_role != role:
            log_event(db, USER_ROLE_CHANGE, target_type="user", target_id=str(user.id),
                      detail={"from": old_role, "to": role, "source": "scim"})
        if old_active != active:
            log_event(db, USER_STATE_CHANGE, target_type="user", target_id=str(user.id),
                      detail={"active": active, "source": "scim"})
        return _scim_json(_user_resource(db, user, request))
    except ValueError as exc:
        db.rollback()
        return _scim_error(400, str(exc))


@router.patch("/Users/{user_id}")
def patch_user(
    user_id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(_require_scim),
    db: Session = Depends(get_db),
) -> JSONResponse:
    user = _get_user(db, user_id)
    if user is None:
        return _scim_error(404, "User not found.")
    operations = body.get("Operations") or body.get("operations")
    if not isinstance(operations, list) or not operations:
        return _scim_error(400, "A non-empty Operations array is required.")

    audit_events: list[tuple[str, dict[str, Any]]] = []
    try:
        for operation in operations:
            if not isinstance(operation, dict):
                return _scim_error(400, "Each PatchOp operation must be an object.")
            op = str(operation.get("op") or "").lower()
            path = str(operation.get("path") or "").strip()
            value = operation.get("value")
            if op not in ("add", "replace", "remove"):
                return _scim_error(400, f"Unsupported PatchOp operation '{op}'.")
            if path in ("active", "urn:ietf:params:scim:schemas:core:2.0:User:active"):
                active = False if op == "remove" else bool(value)
                if user.active != active:
                    audit_events.append((USER_STATE_CHANGE, {"active": active, "source": "scim"}))
                    user.active = active
                    if not active:
                        user.tokens_valid_from = datetime.now(UTC)
            elif path in ("userName", "emails", "emails.value"):
                if op == "remove":
                    return _scim_error(400, "userName cannot be removed.")
                if path == "userName":
                    new_email = str(value or "").strip().lower()
                else:
                    first = value[0] if isinstance(value, list) and value else value
                    new_email = str(first.get("value") if isinstance(first, dict) else first).strip().lower()
                if not new_email or "@" not in new_email:
                    return _scim_error(400, "A valid userName is required.")
                if not _unique_email(db, new_email, exclude_id=user.id):
                    return _scim_error(409, "A user with that userName already exists.")
                user.email = new_email
            elif path in ("roles", "urn:ietf:params:scim:schemas:core:2.0:User:roles"):
                if op == "remove":
                    role = "member"
                elif isinstance(value, list):
                    role = _role_from_body({"roles": value})
                else:
                    role = _role_from_body({"roles": [value]})
                if user.role != role:
                    audit_events.append((USER_ROLE_CHANGE, {
                        "from": user.role, "to": role, "source": "scim",
                    }))
                    user.role = role
            elif path in (
                "name", "name.givenName", "name.familyName", "displayName",
                "externalId", "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User",
            ):
                # Flowsmith stores only the email identity today. Accept these
                # common IdP attributes so provisioning does not fail; they are
                # not persisted in the current schema.
                continue
            elif not path and isinstance(value, dict):
                for key, item in value.items():
                    if key == "active":
                        active = bool(item)
                        if user.active != active:
                            user.active = active
                            if not active:
                                user.tokens_valid_from = datetime.now(UTC)
                    elif key == "userName":
                        new_email = str(item or "").strip().lower()
                        if not _unique_email(db, new_email, exclude_id=user.id):
                            return _scim_error(409, "A user with that userName already exists.")
                        user.email = new_email
            else:
                return _scim_error(400, f"Unsupported PatchOp path '{path}'.")
        _commit(db)
        db.refresh(user)
        for action, detail in audit_events:
            log_event(db, action, target_type="user", target_id=str(user.id), detail=detail)
        return _scim_json(_user_resource(db, user, request))
    except ValueError as exc:
        db.rollback()
        return _scim_error(400, str(exc))


@router.delete("/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    _: None = Depends(_require_scim),
    db: Session = Depends(get_db),
) -> Response:
    user = _get_user(db, user_id)
    if user is None:
        return _scim_error(404, "User not found.")
    if user.active:
        user.active = False
        user.tokens_valid_from = datetime.now(UTC)
        db.commit()
        log_event(db, USER_STATE_CHANGE, target_type="user", target_id=str(user.id),
                  detail={"active": False, "source": "scim"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
