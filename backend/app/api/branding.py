"""Branding and white-labeling configuration API endpoints."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok
from app.audit import log_event
from app.db import get_db
from app.models import User
from app.models.branding import BrandingSetting

router = APIRouter(prefix="/api/branding", tags=["branding"])

HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

DEFAULT_BRANDING: dict[str, Any] = {
    "app_name": "Flowsmith",
    "tagline": "Next-Gen Workflow Automation",
    "logo_url": None,
    "logo_data": None,
    "favicon_url": None,
    "primary_color": "#6366f1",
    "documentation_url": None,
    "support_email": None,
    "copyright_text": None,
    "custom_css": None,
}


def _branding_to_dict(rec: BrandingSetting | None) -> dict[str, Any]:
    if rec is None:
        return dict(DEFAULT_BRANDING)
    return {
        "app_name": rec.app_name or DEFAULT_BRANDING["app_name"],
        "tagline": rec.tagline or DEFAULT_BRANDING["tagline"],
        "logo_url": rec.logo_url,
        "logo_data": rec.logo_data,
        "favicon_url": rec.favicon_url,
        "primary_color": rec.primary_color or DEFAULT_BRANDING["primary_color"],
        "documentation_url": rec.documentation_url,
        "support_email": rec.support_email,
        "copyright_text": rec.copyright_text,
        "custom_css": rec.custom_css,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
    }


class BrandingUpdateRequest(BaseModel):
    app_name: str | None = Field(default=None, max_length=128)
    tagline: str | None = Field(default=None, max_length=255)
    logo_url: str | None = None
    logo_data: str | None = None
    favicon_url: str | None = None
    primary_color: str | None = None
    documentation_url: str | None = Field(default=None, max_length=512)
    support_email: str | None = Field(default=None, max_length=255)
    copyright_text: str | None = Field(default=None, max_length=255)
    custom_css: str | None = Field(default=None, max_length=65536)


@router.get("")
def get_branding(db: Session = Depends(get_db)) -> dict:
    """Public endpoint to fetch active branding configuration for UI rendering."""
    rec = db.scalar(select(BrandingSetting).where(BrandingSetting.id == "default"))
    return ok(_branding_to_dict(rec))


@router.put("")
def update_branding(
    body: BrandingUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Update company branding settings (white-labeling)."""
    # Validation
    if body.primary_color:
        trimmed_color = body.primary_color.strip()
        if not HEX_COLOR_PATTERN.match(trimmed_color):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Invalid primary_color format; expected hex color like #6366f1",
            )

    if body.logo_data and len(body.logo_data) > 5 * 1024 * 1024:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Logo image is too large (maximum 5MB allowed).",
        )

    rec = db.scalar(select(BrandingSetting).where(BrandingSetting.id == "default"))
    if rec is None:
        rec = BrandingSetting(id="default")
        db.add(rec)

    if body.app_name is not None:
        rec.app_name = body.app_name.strip() or DEFAULT_BRANDING["app_name"]
    if body.tagline is not None:
        rec.tagline = body.tagline.strip()
    if body.logo_url is not None:
        rec.logo_url = body.logo_url.strip() if body.logo_url else None
    if body.logo_data is not None:
        rec.logo_data = body.logo_data if body.logo_data else None
    if body.favicon_url is not None:
        rec.favicon_url = body.favicon_url if body.favicon_url else None
    if body.primary_color is not None:
        rec.primary_color = body.primary_color.strip()
    if body.documentation_url is not None:
        rec.documentation_url = body.documentation_url.strip() if body.documentation_url else None
    if body.support_email is not None:
        rec.support_email = body.support_email.strip() if body.support_email else None
    if body.copyright_text is not None:
        rec.copyright_text = body.copyright_text.strip() if body.copyright_text else None
    if body.custom_css is not None:
        rec.custom_css = body.custom_css.strip() if body.custom_css else None

    db.commit()
    db.refresh(rec)

    log_event(
        db,
        "branding.update",
        target_type="system",
        target_id="branding",
        user_id=user.id,
        detail={"app_name": rec.app_name, "has_logo": bool(rec.logo_data or rec.logo_url)},
    )

    return ok(_branding_to_dict(rec))


@router.post("/reset")
def reset_branding(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Reset branding back to Flowsmith defaults."""
    rec = db.scalar(select(BrandingSetting).where(BrandingSetting.id == "default"))
    if rec is not None:
        rec.app_name = DEFAULT_BRANDING["app_name"]
        rec.tagline = DEFAULT_BRANDING["tagline"]
        rec.logo_url = None
        rec.logo_data = None
        rec.favicon_url = None
        rec.primary_color = DEFAULT_BRANDING["primary_color"]
        rec.documentation_url = None
        rec.support_email = None
        rec.copyright_text = None
        rec.custom_css = None
        db.commit()
        db.refresh(rec)

    log_event(
        db,
        "branding.reset",
        target_type="system",
        target_id="branding",
        user_id=user.id,
        detail={"app_name": DEFAULT_BRANDING["app_name"]},
    )

    return ok(_branding_to_dict(rec))
