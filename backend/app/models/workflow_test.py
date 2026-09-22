"""First-class workflow tests (Phase 14).

A WorkflowTest is a saved, repeatable test case for one workflow:

- ``test_data``        trigger items fed to the run
- ``mocks``            HTTP mock rules — matched outbound calls are answered
                       locally and NEVER reach a real provider; unmatched
                       outbound calls are blocked outright (test mode can
                       never mutate production systems)
- ``assertions``       per-node checks evaluated after the run
- ``expected_outputs`` snapshot used by regression assertions (DIFF)

Runs are ordinary executions with ``trigger="test"``; the report lands in
``Execution.results["_tests"]`` as {pass, checks:[...]} where each check
reads PASS / FAIL / DIFF.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

if TYPE_CHECKING:
    pass


class WorkflowTest(Base):
    __tablename__ = "workflow_tests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)

    # Free-form test spec sections (validated loosely at the API edge).
    test_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mocks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    assertions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expected_outputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
