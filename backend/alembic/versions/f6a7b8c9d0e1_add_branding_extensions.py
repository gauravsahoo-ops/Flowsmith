"""Add documentation_url, support_email, copyright_text, and custom_css to branding_settings.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-18 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    insp = sa.inspect(bind)
    columns = [c['name'] for c in insp.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("branding_settings"):
        return

    if not _has_column(bind, 'branding_settings', 'documentation_url'):
        op.add_column('branding_settings', sa.Column('documentation_url', sa.String(length=512), nullable=True))
    if not _has_column(bind, 'branding_settings', 'support_email'):
        op.add_column('branding_settings', sa.Column('support_email', sa.String(length=255), nullable=True))
    if not _has_column(bind, 'branding_settings', 'copyright_text'):
        op.add_column('branding_settings', sa.Column('copyright_text', sa.String(length=255), nullable=True))
    if not _has_column(bind, 'branding_settings', 'custom_css'):
        op.add_column('branding_settings', sa.Column('custom_css', sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("branding_settings"):
        return

    if _has_column(bind, 'branding_settings', 'custom_css'):
        op.drop_column('branding_settings', 'custom_css')
    if _has_column(bind, 'branding_settings', 'copyright_text'):
        op.drop_column('branding_settings', 'copyright_text')
    if _has_column(bind, 'branding_settings', 'support_email'):
        op.drop_column('branding_settings', 'support_email')
    if _has_column(bind, 'branding_settings', 'documentation_url'):
        op.drop_column('branding_settings', 'documentation_url')
