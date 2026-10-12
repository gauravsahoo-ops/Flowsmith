"""User Application Session model.

Tracks active sessions, device info, idle timeouts, and absolute lifetime
for Flowsmith's Smart Session Management.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models import User


def generate_uuid() -> str:
    return str(uuid.uuid4())


class AuthSession(Base):
    """Authoritative user login session tracking tokens, devices, and renewal policies."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_active", "user_id", "is_active"),
        Index("ix_auth_sessions_token_jti", "token_jti", unique=True),
        Index("ix_auth_sessions_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_jti: Mapped[str] = mapped_column(String(64), nullable=False)

    ip_address: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    user_agent: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    device_name: Mapped[str] = mapped_column(String(128), default="Browser", nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remember_device: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    idle_timeout_minutes: Mapped[int] = mapped_column(Integer, default=1440, nullable=False)  # 24 hours
    max_lifetime_minutes: Mapped[int] = mapped_column(Integer, default=10080, nullable=False)  # 7 days

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()
