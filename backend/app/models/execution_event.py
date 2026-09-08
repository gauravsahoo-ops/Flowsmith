"""Execution events (Phase 15, spec 37/28: execution_events).

Durable per-execution event log written by external workers (the
embedded consumer keeps using the in-process bus). The WebSocket
handler falls back to these rows for live node status when the bus has
nothing (spec 10's polling fallback), and the sequence numbers line up
with the bus so the two are interchangeable.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ExecutionEvent(Base):
    __tablename__ = "execution_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now, server_default=func.now()
    )
