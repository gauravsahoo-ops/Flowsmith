"""Workflow auth-state ORM model (auth lifecycle).

One row per (workflow_id, provider): the encrypted token bundle that
Auth Fetch reads and Auth Store upserts. `data` holds the
Fernet-encrypted JSON blob (same keyring as credentials) — ciphertext
at rest, decrypted only inside the node run.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class WorkflowAuthState(Base):
    __tablename__ = "workflow_auth_state"
    __table_args__ = (
        UniqueConstraint("workflow_id", "provider", name="uq_workflow_auth_state_wf_provider"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
