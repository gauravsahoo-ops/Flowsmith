"""Installed connector/template packs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ConnectorPackTombstone(Base):
    """A key that was uninstalled and must be removed from other processes."""

    __tablename__ = "connector_pack_tombstones"

    connector_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    uninstalled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ConnectorPack(Base):
    __tablename__ = "connector_packs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connector_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0.0")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="api")
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    template_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The generated provider/definition/connector sources are stored so every
    # API/worker process can materialize the same connector without relying on
    # a shared container filesystem.
    generated_sources: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    dependencies: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    signed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    signing_key_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    installed_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
