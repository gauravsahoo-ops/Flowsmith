"""files table for S3-compatible object storage (audit phases 19-20)

Stores metadata for uploaded documents/artifacts; the actual bytes live
in the configured object store (local filesystem or S3). Workspace
ownership is enforced at the API layer.

Revision ID: 7c2d9e4b1af3
Revises: f9a3c1d8e6b2
Create Date: 2026-08-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c2d9e4b1af3'
down_revision: Union[str, Sequence[str], None] = 'f9a3c1d8e6b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "files"):
        op.create_table(
            'files',
            sa.Column('id', sa.String(length=64), primary_key=True),
            sa.Column('workspace_id', sa.String(length=64), nullable=True),
            sa.Column('owner_user_id', sa.Integer(), nullable=False),
            sa.Column('filename', sa.String(length=512), nullable=False),
            sa.Column('mime_type', sa.String(length=255), nullable=False, server_default="application/octet-stream"),
            sa.Column('size', sa.Integer(), nullable=False, server_default="0"),
            sa.Column('object_key', sa.String(length=512), nullable=False, unique=True),
            sa.Column('metadata_', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
            sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ),
        )
        op.create_index(op.f('ix_files_owner_user_id'), 'files', ['owner_user_id'], unique=False)
        op.create_index(op.f('ix_files_workspace_id'), 'files', ['workspace_id'], unique=False)
        op.create_index(op.f('ix_files_object_key'), 'files', ['object_key'], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "files"):
        op.drop_index(op.f('ix_files_object_key'), table_name='files')
        op.drop_index(op.f('ix_files_workspace_id'), table_name='files')
        op.drop_index(op.f('ix_files_owner_user_id'), table_name='files')
        op.drop_table('files')
