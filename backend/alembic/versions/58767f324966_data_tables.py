"""data tables: table metadata, columns, rows (JSONB)

Revision ID: 58767f324966
Revises: 7c2d9e4b1af3
Create Date: 2026-08-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '58767f324966'
down_revision: Union[str, Sequence[str], None] = '7c2d9e4b1af3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    # data_tables
    if not _has_table(bind, "data_tables"):
        op.create_table(
            'data_tables',
            sa.Column('id', sa.String(length=64), primary_key=True),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=False, server_default=""),
            sa.Column('workspace_id', sa.String(length=64), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.UniqueConstraint('workspace_id', 'name', name='uq_data_table_workspace_name'),
        )
        op.create_index(op.f('ix_data_tables_workspace_id'), 'data_tables', ['workspace_id'], unique=False)
        op.create_index(op.f('ix_data_tables_user_id'), 'data_tables', ['user_id'], unique=False)

    if not _has_table(bind, "data_table_columns"):
        op.create_table(
            'data_table_columns',
            sa.Column('id', sa.String(length=64), primary_key=True),
            sa.Column('table_id', sa.String(length=64), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('type', sa.String(length=32), nullable=False),
            sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('default_value', sa.Text(), nullable=True),
            sa.Column('position', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['table_id'], ['data_tables.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('table_id', 'name', name='uq_column_table_name'),
        )
        op.create_index(op.f('ix_data_table_columns_table_id'), 'data_table_columns', ['table_id'], unique=False)

    if not _has_table(bind, "data_table_rows"):
        op.create_table(
            'data_table_rows',
            sa.Column('id', sa.String(length=64), primary_key=True),
            sa.Column('table_id', sa.String(length=64), nullable=False),
            sa.Column('data', sa.JSON(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['table_id'], ['data_tables.id'], ondelete='CASCADE'),
        )
        op.create_index(op.f('ix_data_table_rows_table_id'), 'data_table_rows', ['table_id'], unique=False)
        # GIN index for JSONB searching (optional, for large tables)
        # op.create_index('ix_data_table_rows_data_gin', 'data_table_rows', ['data'], postgresql_using='gin')


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "data_table_rows"):
        op.drop_index(op.f('ix_data_table_rows_table_id'), table_name='data_table_rows')
        op.drop_table('data_table_rows')
    if _has_table(bind, "data_table_columns"):
        op.drop_index(op.f('ix_data_table_columns_table_id'), table_name='data_table_columns')
        op.drop_table('data_table_columns')
    if _has_table(bind, "data_tables"):
        op.drop_index(op.f('ix_data_tables_user_id'), table_name='data_tables')
        op.drop_index(op.f('ix_data_tables_workspace_id'), table_name='data_tables')
        op.drop_table('data_tables')
