"""Branding and white-labeling configuration model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BrandingSetting(Base):
    """Per-user custom branding configuration.

    The row with id ``default`` (``user_id is NULL``) is the platform fallback
    used before login. Every authenticated user has at most one private brand.
    """

    __tablename__ = "branding_settings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=True,
    )
    # Legacy organization scope retained for migration/downgrade; new rows use
    # user_id and leave this NULL.
    organization_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    app_name: Mapped[str] = mapped_column(String(128), default="Flowsmith", nullable=False)
    tagline: Mapped[str] = mapped_column(
        String(255), default="Next-Gen Workflow Automation", nullable=False
    )
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # base64 data URI or SVG
    favicon_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_color: Mapped[str] = mapped_column(String(32), default="#6366f1", nullable=False)
    documentation_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    support_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    copyright_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    custom_css: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
