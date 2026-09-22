"""Job queue record (Phase 15, spec 13/34/58): one row per queued execution.

The queue is the transport layer; the executions table stays the
authoritative record of execution state (spec 25.3). Jobs are claimed
atomically by workers (any worker can run any job — stateless), and
crashed workers are detected via a stale heartbeat and the job is
re-queued (spec 34.1).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, JSON, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Lifecycle: queued -> claimed -> done | failed
# A claimed job whose heartbeat went stale is re-queued by recovery.
QUEUED = "queued"
CLAIMED = "claimed"
DONE = "done"
FAILED = "failed"
JOB_TERMINAL = frozenset({DONE, FAILED})


class Job(Base):
    __tablename__ = "jobs"
    # Mirrors migration a1b2c3d4e5f6 (ix_jobs_claim): covers the worker
    # claim query WHERE status='queued' AND (next_retry_at IS NULL OR
    # next_retry_at <= :now) ORDER BY created_at, id.
    __table_args__ = (
        Index(
            "ix_jobs_claim",
            "status", "next_retry_at", "created_at", "id",
            postgresql_where=text("status = 'queued'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=QUEUED, index=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Earliest time the job may be claimed again after a recovery requeue
    # (exponential retry backoff, audit phase 8). NULL == claimable now.
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
