"""Add organization-wide MFA requirement.

Revision ID: d1e2f3a4b5c6
Revises: c4e5f6a7b8d9
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c4e5f6a7b8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table("organizations"):
        return set()
    return {column["name"] for column in inspector.get_columns("organizations")}


def upgrade() -> None:
    if "require_mfa" not in _columns(op.get_bind()):
        op.add_column(
            "organizations",
            sa.Column(
                "require_mfa",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade() -> None:
    if "require_mfa" in _columns(op.get_bind()):
        op.drop_column("organizations", "require_mfa")
