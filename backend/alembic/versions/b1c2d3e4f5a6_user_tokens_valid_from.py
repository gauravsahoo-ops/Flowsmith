"""Add users.tokens_valid_from (bearer-token invalidation on password reset).

Revision ID: b1c2d3e4f5a6
Revises: d4a1c7e9f3b5
Create Date: 2026-10-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'd4a1c7e9f3b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('tokens_valid_from', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('users', 'tokens_valid_from')
