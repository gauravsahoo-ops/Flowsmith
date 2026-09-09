"""Admin user management (security phase): list users, change
role/active. Only admins. The last active admin cannot be demoted or
deactivated, and admins cannot deactivate themselves.
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
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/api/users", tags=["users"])

VALID_ROLES = {"admin", "member"}


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin privileges required.")
    return user


def _to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "active": user.active,
        "created_at": user.created_at,
    }


@router.get("")
def list_users(
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    users = db.scalars(select(User).order_by(User.created_at).limit(limit)).all()
    return ok([_to_dict(u) for u in users])


class UserUpdateRequest(BaseModel):
    role: str | None = None
    active: bool | None = None


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdateRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if body.role is not None and body.role not in VALID_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "role must be 'admin' or 'member'.")
    if body.role is None and body.active is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to update.")

    if target.id == admin.id:
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
                "Cannot change the last active admin.",
            )

    if body.role is not None and body.role != target.role:
        log_event(db, USER_ROLE_CHANGE, target_type="user", target_id=str(target.id),
                  user_id=admin.id, detail={"role": body.role, "old_role": target.role})
        target.role = body.role
    if body.active is not None and body.active != target.active:
        log_event(db, USER_STATE_CHANGE, target_type="user", target_id=str(target.id),
                  user_id=admin.id, detail={"active": body.active, "old_active": target.active})
        target.active = body.active
    db.commit()
    db.refresh(target)
    return ok(_to_dict(target))
