"""Merge the telemetry and core migration heads.

Revision ID: b7c8d9e0f1a2
Revises: a9b8c7d6e5f4, e9f0a1b2c3d4
Create Date: 2026-11-12 00:00:00.000000

The repository contained two independent Alembic branches: the telemetry
branch ending at ``a9b8c7d6e5f4`` and the core/connector branch ending at
``e9f0a1b2c3d4``. ``alembic upgrade head`` cannot resolve two heads, so this
empty merge revision joins them. The approval migration extends the merged
head.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "b7c8d9e0f1a2"
down_revision: tuple[str, str] | Sequence[str] | None = (
    "a9b8c7d6e5f4",
    "e9f0a1b2c3d4",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
