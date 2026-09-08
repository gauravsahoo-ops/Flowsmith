"""Subscription model (Phase 34: commercial/SaaS foundation).

One subscription per organization. Rows are created lazily on first
access (defaulting to the free plan), so existing organizations never
need a data migration. Stripe identifiers are stored when a checkout or
webhook touches the organization.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

FREE_PLAN = "free"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(32), default=FREE_PLAN, nullable=False)
    # active | trialing | past_due | canceled
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    stripe_customer_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    stripe_subscription_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    stripe_checkout_session_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_subscription_org"),
    )
