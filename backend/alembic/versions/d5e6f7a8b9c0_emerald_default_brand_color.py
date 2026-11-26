"""Default platform brand accent to emerald green.

Revision ID: d5e6f7a8b9c0
Revises: b2c3d4e5f6a7
Create Date: 2026-11-26 15:45:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_DEFAULT = "#6366f1"
NEW_DEFAULT = "#10b981"


def upgrade() -> None:
    # Only rewrite the legacy platform default; explicit custom colors remain.
    op.execute(
        f"UPDATE branding_settings SET primary_color = '{NEW_DEFAULT}' "
        f"WHERE primary_color = '{OLD_DEFAULT}'"
    )


def downgrade() -> None:
    op.execute(
        f"UPDATE branding_settings SET primary_color = '{OLD_DEFAULT}' "
        f"WHERE primary_color = '{NEW_DEFAULT}'"
    )
