"""rag_collections (Phase 18: production RAG)

Revision ID: d7f1a2b3c4e5
Revises: b51d7c8a90f2
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7f1a2b3c4e5'
down_revision: Union[str, Sequence[str], None] = 'b51d7c8a90f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('rag_collections',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('store_name', sa.String(length=80), nullable=False),
    sa.Column('owner_user_id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.String(length=64), nullable=True),
    sa.Column('embedding_model', sa.String(length=120), nullable=False),
    sa.Column('dim', sa.Integer(), nullable=True),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('metadata', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_rag_collections_owner_user_id'), 'rag_collections', ['owner_user_id'], unique=False)
    op.create_index(op.f('ix_rag_collections_workspace_id'), 'rag_collections', ['workspace_id'], unique=False)
    op.create_unique_constraint('uq_rag_collections_store_name', 'rag_collections', ['store_name'])


def downgrade() -> None:
    op.drop_constraint('uq_rag_collections_store_name', 'rag_collections', type_='unique')
    op.drop_index(op.f('ix_rag_collections_workspace_id'), table_name='rag_collections')
    op.drop_index(op.f('ix_rag_collections_owner_user_id'), table_name='rag_collections')
    op.drop_table('rag_collections')
