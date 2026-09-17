"""Add branding_settings table for white-labeling and custom company branding.

Revision ID: e5f6a7b8c9d0
Revises: d2e6f8a0b1c3
Create Date: 2026-09-17 23:55:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd2e6f8a0b1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "branding_settings"):
        op.create_table(
            'branding_settings',
            sa.Column('id', sa.String(length=64), primary_key=True),
            sa.Column('app_name', sa.String(length=128), nullable=False, server_default='Flowsmith'),
            sa.Column('tagline', sa.String(length=255), nullable=False, server_default='Next-Gen Workflow Automation'),
            sa.Column('logo_url', sa.Text(), nullable=True),
            sa.Column('logo_data', sa.Text(), nullable=True),
            sa.Column('favicon_url', sa.Text(), nullable=True),
            sa.Column('primary_color', sa.String(length=32), nullable=False, server_default='#6366f1'),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "branding_settings"):
        op.drop_table('branding_settings')
