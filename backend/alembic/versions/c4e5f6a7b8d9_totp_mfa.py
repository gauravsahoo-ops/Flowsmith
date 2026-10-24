"""Add TOTP multi-factor authentication state to users.

Revision ID: c4e5f6a7b8d9
Revises: a3c4d5e6f7b8
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e5f6a7b8d9"
down_revision: Union[str, Sequence[str], None] = "a3c4d5e6f7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        return set()
    return {column["name"] for column in inspector.get_columns("users")}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind)
    if "mfa_enabled" not in existing:
        op.add_column(
            "users",
            sa.Column(
                "mfa_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "mfa_secret" not in existing:
        op.add_column("users", sa.Column("mfa_secret", sa.Text(), nullable=True))
    if "mfa_last_step" not in existing:
        op.add_column("users", sa.Column("mfa_last_step", sa.Integer(), nullable=True))
    if "mfa_recovery_hashes" not in existing:
        op.add_column("users", sa.Column("mfa_recovery_hashes", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind)
    if "mfa_recovery_hashes" in existing:
        op.drop_column("users", "mfa_recovery_hashes")
    if "mfa_last_step" in existing:
        op.drop_column("users", "mfa_last_step")
    if "mfa_secret" in existing:
        op.drop_column("users", "mfa_secret")
    if "mfa_enabled" in existing:
        op.drop_column("users", "mfa_enabled")
