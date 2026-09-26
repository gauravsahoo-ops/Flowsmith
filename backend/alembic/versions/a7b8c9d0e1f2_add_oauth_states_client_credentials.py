"""Add client_id and client_secret to oauth_states table.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-23 18:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    insp = sa.inspect(bind)
    columns = [c['name'] for c in insp.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("oauth_states"):
        return

    if not _has_column(bind, 'oauth_states', 'client_id'):
        op.add_column('oauth_states', sa.Column('client_id', sa.String(length=255), nullable=True))
    if not _has_column(bind, 'oauth_states', 'client_secret'):
        op.add_column('oauth_states', sa.Column('client_secret', sa.String(length=512), nullable=True))
    if not _has_column(bind, 'oauth_states', 'name'):
        op.add_column('oauth_states', sa.Column('name', sa.String(length=255), nullable=True))
    if not _has_column(bind, 'oauth_states', 'allowed_domains'):
        op.add_column('oauth_states', sa.Column('allowed_domains', sa.String(length=512), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("oauth_states"):
        return

    if _has_column(bind, 'oauth_states', 'allowed_domains'):
        op.drop_column('oauth_states', 'allowed_domains')
    if _has_column(bind, 'oauth_states', 'name'):
        op.drop_column('oauth_states', 'name')
    if _has_column(bind, 'oauth_states', 'client_secret'):
        op.drop_column('oauth_states', 'client_secret')
    if _has_column(bind, 'oauth_states', 'client_id'):
        op.drop_column('oauth_states', 'client_id')
