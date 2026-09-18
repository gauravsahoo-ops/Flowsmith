"""Branding and white-labeling configuration model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BrandingSetting(Base):
    """System-wide or organization/workspace custom branding configuration."""

    __tablename__ = "branding_settings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
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
