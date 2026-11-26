"""User account endpoints under a per-user tenant model.

A normal account can see only itself. Platform operator accounts (the
instance ``admin`` role used for deployment/identity safety) may list and
manage all accounts. Organization roles never grant visibility into another
user's account.

Role and activation changes are platform-level because ``users.role`` and
``users.active`` apply to the account everywhere. Users cannot promote or
demote themselves, and the last active operator account cannot be removed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok
from app.audit import USER_ROLE_CHANGE, USER_STATE_CHANGE, log_event
from app.config import get_settings
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/api/users", tags=["users"])

VALID_ROLES = {"admin", "member"}


def _to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "active": user.active,
        "created_at": user.created_at,
    }


def _is_operator(user: User) -> bool:
    return (user.role or "").lower() == "admin"


@router.get("")
def list_users(
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    if _is_operator(actor):
        users = db.scalars(
            select(User).order_by(User.created_at).limit(limit)
        ).all()
    else:
        users = [actor]
    return ok([_to_dict(u) for u in users])


class UserUpdateRequest(BaseModel):
    role: str | None = None
    active: bool | None = None


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdateRequest,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not _is_operator(actor):
        if user_id != actor.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Account role and activation are managed at the platform level.",
        )

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")

    settings = get_settings()
    if (
        target.id != actor.id
        and settings.app_env == "production"
        and settings.operator_mfa_required
        and not actor.mfa_enabled
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Operator MFA enrollment is required before changing another account.",
        )

    if body.role is not None and body.role not in VALID_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "role must be 'admin' or 'member'.")
    if body.role is None and body.active is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to update.")

    if target.id == actor.id:
        if body.active is False:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You cannot deactivate your own account.")
        if body.role == "member":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You cannot demote your own account.")

    if body.role == "member" or body.active is False:
        remaining_admins = db.scalar(
            select(func.count()).select_from(User).where(
                User.role == "admin",
                User.active.is_(True),
                User.id != target.id,
            )
        ) or 0
        if remaining_admins == 0:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Cannot change the last active operator account.",
            )

    role_changed = False
    if body.role is not None and body.role != target.role:
        role_changed = True
        log_event(db, USER_ROLE_CHANGE, target_type="user", target_id=str(target.id),
                  user_id=actor.id, detail={"role": body.role, "old_role": target.role})
        target.role = body.role

    active_changed = False
    if body.active is not None and body.active != target.active:
        active_changed = True
        log_event(db, USER_STATE_CHANGE, target_type="user", target_id=str(target.id),
                  user_id=actor.id, detail={"active": body.active, "old_active": target.active})
        target.active = body.active
    db.commit()

    # The affected account must be able to see platform-operator changes in
    # its own audit trail.
    if target.id != actor.id:
        if role_changed:
            log_event(
                db, USER_ROLE_CHANGE, target_type="user", target_id=str(target.id),
                user_id=target.id,
                detail={"actor_user_id": actor.id, "by_operator": True,
                        "role": body.role},
            )
        if active_changed:
            log_event(
                db, USER_STATE_CHANGE, target_type="user", target_id=str(target.id),
                user_id=target.id,
                detail={"actor_user_id": actor.id, "by_operator": True,
                        "active": body.active},
            )

    db.refresh(target)
    return ok(_to_dict(target))
